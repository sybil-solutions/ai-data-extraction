import contextlib
import io
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import extract_zcode


FIXTURE = Path(__file__).parent / "fixtures" / "zcode" / "session.json"
SCRIPT = Path(extract_zcode.__file__).resolve()


def create_database(path, optional=True):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    connection = sqlite3.connect(path)
    session = fixture["session"]
    columns = list(session) if optional else ["id", "time_created"]
    definitions = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(f"CREATE TABLE session ({definitions})")
    connection.execute(
        f"INSERT INTO session VALUES ({placeholders})",
        [session[column] for column in columns],
    )
    connection.execute(
        "CREATE TABLE message (id, session_id, time_created, data)"
    )
    connection.execute(
        "CREATE TABLE part (id, session_id, message_id, time_created, data)"
    )
    for message in fixture["messages"]:
        connection.execute(
            "INSERT INTO message VALUES (?, ?, ?, ?)",
            (message["id"], session["id"], message["time_created"], json.dumps(message["data"])),
        )
        for index, part in enumerate(message["parts"]):
            connection.execute(
                "INSERT INTO part VALUES (?, ?, ?, ?, ?)",
                (f'{message["id"]}-{index:03d}', session["id"], message["id"], index, json.dumps(part)),
            )
    if optional:
        connection.execute(
            "CREATE TABLE session_target "
            "(session_id, objective, status, token_budget, tokens_used, time_used_seconds)"
        )
        connection.execute(
            "INSERT INTO session_target VALUES (?, ?, ?, ?, ?, ?)",
            (session["id"], *fixture["goal"].values()),
        )
        connection.execute(
            "CREATE TABLE todo (session_id, content, status, priority, position)"
        )
        for index, todo in reversed(list(enumerate(fixture["todos"]))):
            connection.execute(
                "INSERT INTO todo VALUES (?, ?, ?, ?, ?)",
                (session["id"], *todo.values(), index),
            )
    connection.commit()
    connection.close()
    return fixture


class ExtractZcodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "db.sqlite"
        self.fixture = create_database(self.path)

    def extract(self, path=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return extract_zcode.extract_conversations(path or self.path)

    def test_extracts_messages_reasoning_tools_and_attachments(self):
        path, conversations = self.extract()
        self.assertEqual(path, self.path)
        self.assertEqual(len(conversations), 1)
        user, assistant = conversations[0]["messages"]
        self.assertEqual(user["role"], "user")
        self.assertEqual(user["timestamp"], 1002)
        self.assertEqual(user["content"], "Synthetic question")
        self.assertEqual(user["attachments"], [{
            "filename": "sample.txt", "mime": "text/plain", "url": "file:///work/sample.txt"
        }])
        self.assertEqual(assistant["timestamp"], 1004)
        self.assertEqual(assistant["content"], "First line\u2028middle\u2029end\nSecond line")
        self.assertEqual(assistant["reasoning"], "First thought\nSecond thought")
        self.assertEqual(assistant["parent_id"], "message-user")
        for field in extract_zcode.MESSAGE_FIELDS:
            self.assertEqual(assistant[field], self.fixture["messages"][1]["data"][field])
        self.assertEqual([call["status"] for call in assistant["tool_calls"]], ["completed", "error", "running"])
        self.assertEqual(assistant["tool_results"], [
            {"tool_call_id": "call-complete", "tool": "read", "output": "Synthetic output"},
            {"tool_call_id": "call-error", "tool": "bash", "error": "Synthetic failure"},
        ])

    def test_preserves_session_goals_todos_and_parent_metadata(self):
        _, conversations = self.extract()
        conversation = conversations[0]
        self.assertEqual(conversation["source"], "zcode")
        self.assertEqual(conversation["session_id"], self.fixture["session"]["id"])
        self.assertEqual(conversation["parent_session_id"], "session-parent")
        self.assertEqual(conversation["created_at"], 1000)
        self.assertEqual(conversation["updated_at"], 2000)
        for field in ("task_type", "slug", "directory", "title", "title_source", "version", "share_url", "time_archived"):
            self.assertEqual(conversation[field], self.fixture["session"][field])
        self.assertEqual(conversation["db_path"], str(self.path))
        self.assertEqual(conversation["goal"], self.fixture["goal"])
        self.assertEqual(conversation["todos"], self.fixture["todos"])

    def test_extracts_without_optional_session_columns_or_tables(self):
        path = self.root / "minimal.sqlite"
        create_database(path, optional=False)
        _, conversations = self.extract(path)
        self.assertEqual(len(conversations[0]["messages"]), 2)
        self.assertNotIn("goal", conversations[0])
        self.assertNotIn("todos", conversations[0])

    def test_skips_malformed_records_without_exposing_record_content(self):
        sentinel = "PRIVATE_SYNTHETIC_SENTINEL"
        with sqlite3.connect(self.path) as connection:
            for index, data in enumerate(("{", "[]", "null", json.dumps(sentinel))):
                connection.execute("INSERT INTO message VALUES (?, ?, ?, ?)",
                                   (f"{sentinel}-{index}", "session-main", 1010 + index, data))
                connection.execute("INSERT INTO part VALUES (?, ?, ?, ?, ?)",
                                   (f"{sentinel}-{index}", "session-main", "message-assistant", 100 + index, data))
            connection.execute("INSERT INTO message VALUES (?, ?, ?, ?)",
                               ("null-time", "session-main", 1020, '{"role": "assistant", "time": null}'))
            connection.execute("INSERT INTO part VALUES (?, ?, ?, ?, ?)",
                               ("null-state", "session-main", "null-time", 1, '{"type": "tool", "state": null}'))
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            _, conversations = extract_zcode.extract_conversations(self.path)
        self.assertEqual(len(conversations), 1)
        self.assertEqual(len(conversations[0]["messages"]), 3)
        self.assertEqual(conversations[0]["messages"][-1]["timestamp"], 1020)
        self.assertEqual(conversations[0]["messages"][1]["reasoning"], "First thought\nSecond thought")
        self.assertNotIn(sentinel, output.getvalue() + errors.getvalue())
        self.assertEqual(set(errors.getvalue().splitlines()), {
            "Warning: malformed messages: 4",
            "Warning: malformed parts: 4",
            "Warning: malformed tool states: 1",
        })

    def test_uri_reserved_characters_in_database_path(self):
        path = self.root / "database #query? test.sqlite"
        create_database(path)
        _, conversations = self.extract(path)
        self.assertEqual(len(conversations), 1)

    def test_snapshot_includes_committed_live_wal_without_source_changes(self):
        with sqlite3.connect(self.path) as writer:
            self.assertEqual(writer.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("UPDATE session SET title = 'Committed WAL title'")
            writer.commit()
            wal = Path(str(self.path) + "-wal")
            self.assertTrue(wal.exists())
            before = (self.path.read_bytes(), wal.read_bytes())
            _, conversations = self.extract()
            self.assertEqual(conversations[0]["title"], "Committed WAL title")
            self.assertEqual((self.path.read_bytes(), wal.read_bytes()), before)
            self.assertEqual(writer.execute("SELECT title FROM session").fetchone()[0], "Committed WAL title")

    def test_snapshot_removes_temporary_database_after_success(self):
        with extract_zcode.open_snapshot(self.path) as connection:
            self.assertIs(connection.row_factory, sqlite3.Row)
            snapshot = Path(connection.execute("PRAGMA database_list").fetchone()[2])
            self.assertNotEqual(snapshot, self.path)
            self.assertTrue(snapshot.is_file())
        self.assertFalse(snapshot.exists())

    def test_snapshot_removes_temporary_database_after_error(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
            with extract_zcode.open_snapshot(self.path) as connection:
                snapshot = Path(connection.execute("PRAGMA database_list").fetchone()[2])
                raise RuntimeError("synthetic failure")
        self.assertFalse(snapshot.exists())

    def test_missing_database_returns_no_conversations(self):
        missing = self.root / "missing.sqlite"
        self.assertEqual(self.extract(missing), (None, []))
        self.assertFalse(missing.exists())

    def test_json_line_escapes_unicode_line_separators(self):
        value = {"content": "first\u2028second\u2029third"}
        line = extract_zcode.json_line(value)
        self.assertEqual(len(line.splitlines()), 1)
        self.assertIn("\\u2028", line)
        self.assertIn("\\u2029", line)
        self.assertEqual(json.loads(line), value)

    def test_cli_custom_database_writes_parseable_jsonl(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(self.path)],
            cwd=self.root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = list((self.root / "extracted_data").glob("zcode_conversations_*.jsonl"))
        self.assertEqual(len(outputs), 1)
        lines = outputs[0].read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(len(json.loads(lines[0])["messages"]), 2)

    def test_cli_missing_database_fails_without_creating_it(self):
        path = self.root / "missing.sqlite"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--db", str(path)],
            cwd=self.root, capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(path.exists())
        self.assertFalse((self.root / "extracted_data").exists())


if __name__ == "__main__":
    unittest.main()

import json
import os
import tempfile
import unittest
from pathlib import Path

from extract_grok import discover_sessions, extract_session, find_session_roots


class ExtractGrokTests(unittest.TestCase):
    def _write_json(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def _write_jsonl(self, path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_extracts_chat_history_updates_metadata_and_subagents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "sessions"
            group = root / "%2FUsers%2Fdev%2Fgrok-project"
            sdir = group / "0192b1a0-0000-7000-8000-000000000001"
            sdir.mkdir(parents=True)

            self._write_json(sdir / "summary.json", {
                "id": "0192b1a0-0000-7000-8000-000000000001",
                "title": "Fix parser edge case",
                "summary": "Fixed parser bug and ran tests",
                "recap": "All tests green",
                "model": "grok-4.6",
                "parent_session_id": "0192b190-0000-7000-8000-000000000000",
                "created_at": "2026-10-20T10:00:00Z",
                "updated_at": "2026-10-20T10:05:00Z",
            })
            (sdir / "system_prompt.txt").write_text("You are Grok Build.", encoding="utf-8")
            self._write_json(sdir / "tool_definitions.json", [
                {"name": "edit_file", "description": "Edit a file"},
                {"function": {"name": "run_bash"}},
            ])
            self._write_json(sdir / "plan.json", {"todos": [{"id": "1", "title": "Fix bug", "status": "completed"}]})
            self._write_json(sdir / "signals.json", {
                "turns": 2,
                "tool_calls": 1,
                "token_usage": {"input_tokens": 1200, "output_tokens": 350, "total_tokens": 1550},
            })
            self._write_jsonl(sdir / "rewind_points.jsonl", [{"turn": 0, "prompt": "Fix parser"}])
            self._write_jsonl(sdir / "feedback.jsonl", [{"rating": "up", "comment": "clean fix"}])
            self._write_json(sdir / "subagents" / "sub-1" / "meta.json", {
                "session_id": "0192b1a1-0000-7000-8000-000000000002",
                "role": "verifier",
            })
            self._write_jsonl(sdir / "chat_history.jsonl", [
                {"role": "user", "content": "Fix parser.py", "timestamp": 1792490400000},
                {
                    "role": "assistant",
                    "model": "grok-4.6",
                    "reasoning": "Inspect and patch parser.py.",
                    "content": "Patching parser.py now.",
                    "tool_calls": [{
                        "id": "call-1",
                        "function": {"name": "edit_file", "arguments": {"path": "src/parser.py", "diff": "+x"}},
                    }],
                    "usage": {"input_tokens": 600, "output_tokens": 150},
                    "timestamp": 1792490405000,
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "name": "edit_file",
                    "content": "Applied patch to src/parser.py",
                    "timestamp": 1792490406000,
                },
                {
                    "role": "assistant",
                    "model": "grok-4.6",
                    "content": "Fixed src/parser.py.",
                    "timestamp": 1792490410000,
                },
            ])
            self._write_jsonl(sdir / "updates.jsonl", [
                {"sessionUpdate": "tool_call", "toolCallId": "call-1", "name": "edit_file", "locations": [{"path": "tests/test_parser.py"}]},
            ])

            conv = extract_session(sdir, group)
            self.assertIsNotNone(conv)
            self.assertEqual(conv["source"], "grok")
            self.assertEqual(conv["session_id"], "0192b1a0-0000-7000-8000-000000000001")
            self.assertEqual(conv["project_path"], "/Users/dev/grok-project")
            self.assertEqual(conv["title"], "Fix parser edge case")
            self.assertEqual(conv["parent_session_id"], "0192b190-0000-7000-8000-000000000000")
            self.assertEqual(conv["system_prompt"], "You are Grok Build.")
            self.assertEqual(conv["tools"], ["edit_file", "run_bash"])
            self.assertEqual(conv["token_usage"]["total_tokens"], 1550)
            self.assertEqual(len(conv["subagents"]), 1)
            self.assertEqual(conv["files_touched"], ["tests/test_parser.py", "src/parser.py"])
            self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "tool", "assistant"])
            self.assertEqual(conv["messages"][1]["reasoning"], "Inspect and patch parser.py.")

    def test_parses_acp_updates_when_chat_history_absent_and_reads_cwd_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("GROK_HOME")
            os.environ["GROK_HOME"] = tmp
            try:
                group = Path(tmp) / "sessions" / "long-slug-8f91a2"
                group.mkdir(parents=True)
                (group / ".cwd").write_text("/workspace/deep/monorepo/service\n", encoding="utf-8")
                sdir = group / "sess-acp-only"
                self._write_jsonl(sdir / "updates.jsonl", [
                    {"sessionUpdate": "user_message", "content": [{"type": "text", "text": "Run tests"}], "timestamp": "2026-10-20T12:00:00Z"},
                    {"sessionUpdate": "agent_thought", "text": "Running pytest.", "model": "grok-4.6"},
                    {"sessionUpdate": "tool_call", "toolCallId": "tc-9", "name": "bash", "rawInput": {"cmd": "pytest", "file_path": "tests/run.py"}, "rawOutput": "1 passed", "status": "completed"},
                    {"sessionUpdate": "agent_message", "content": "All tests passed.", "model": "grok-4.6", "timestamp": "2026-10-20T12:00:05Z"},
                ])
                found = list(discover_sessions(find_session_roots()))
                self.assertEqual(len(found), 1)
                conv = extract_session(found[0][0], found[0][1])
            finally:
                if old_env is None:
                    os.environ.pop("GROK_HOME", None)
                else:
                    os.environ["GROK_HOME"] = old_env

            self.assertEqual(conv["project_path"], "/workspace/deep/monorepo/service")
            self.assertEqual([m["role"] for m in conv["messages"]], ["user", "assistant", "assistant", "tool", "assistant"])
            self.assertEqual(conv["files_touched"], ["tests/run.py"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Extract ZCode conversations from a read-only SQLite snapshot.

The default database is ~/.zcode/cli/db/db.sqlite. Output uses one
conversation per line in extracted_data/zcode_conversations_<timestamp>.jsonl.
Future ZCode updates can change the schema and require parser changes.
"""

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile


DB_PATH = Path.home() / '.zcode' / 'cli' / 'db' / 'db.sqlite'
MESSAGE_FIELDS = ('modelID', 'providerID', 'mode', 'agent', 'cost', 'tokens',
                  'path', 'summary', 'error', 'finish', 'variant')
SKIP_PART_TYPES = {'step-start', 'step-finish', 'timeline', 'compaction'}
_LINE_SEPARATORS = str.maketrans({'\u2028': '\\u2028', '\u2029': '\\u2029'})


def json_line(obj):
    """Serialize one JSONL record, including escaped Unicode line separators."""
    return json.dumps(obj, ensure_ascii=False).translate(_LINE_SEPARATORS)


@contextmanager
def open_snapshot(db_path):
    """Back up committed SQLite data, including WAL rows, into a temporary file."""
    source = snapshot = None
    with tempfile.TemporaryDirectory(prefix='zcode_extract_') as temporary:
        try:
            source = sqlite3.connect(
                Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=5.0)
            snapshot = sqlite3.connect(Path(temporary) / 'snapshot.sqlite')
            source.backup(snapshot)
            source.close()
            source = None
            snapshot.row_factory = sqlite3.Row
            snapshot.execute('PRAGMA query_only=ON')
            yield snapshot
        finally:
            if source is not None:
                source.close()
            if snapshot is not None:
                snapshot.close()


def _columns(conn, table):
    return {row[1] for row in conn.execute('PRAGMA table_info(' + table + ')')}


def _check_schema(conn):
    required = {
        'session': {'id', 'time_created'},
        'message': {'id', 'session_id', 'time_created', 'data'},
        'part': {'id', 'session_id', 'message_id', 'time_created', 'data'},
    }
    for table, columns in required.items():
        if not columns.issubset(_columns(conn, table)):
            raise ValueError('Unsupported ZCode database schema: ' + table)


def _object(raw, warnings, category):
    try:
        value = json.loads(raw)
    except (ValueError, TypeError, UnicodeError):
        value = None
    if not isinstance(value, dict):
        warnings[category] += 1
        return None
    return value


def apply_part(part_data, message, all_content, warnings=None):
    """Add text, reasoning, tools, or an attachment to a message."""
    if warnings is None:
        warnings = Counter()
    if not isinstance(part_data, dict) or not isinstance(part_data.get('type'), str):
        warnings['parts'] += 1
        return
    part_type = part_data['type']
    text = part_data.get('text', '')
    if not isinstance(text, str):
        if text is not None:
            warnings['part fields'] += 1
        text = ''

    if part_type == 'text':
        if text:
            message.setdefault('_content_parts', []).append(text)
            all_content.append(text)
    elif part_type == 'reasoning':
        if text:
            message.setdefault('_reasoning_parts', []).append(text)
    elif part_type == 'tool':
        state = part_data.get('state')
        if not isinstance(state, dict):
            warnings['tool states'] += 1
            state = {}
        message.setdefault('tool_calls', []).append({
            'id': part_data.get('callID'),
            'name': part_data.get('tool'),
            'input': state.get('input'),
            'status': state.get('status'),
        })
        result = {'tool_call_id': part_data.get('callID'),
                  'tool': part_data.get('tool')}
        if state.get('status') == 'completed' and 'output' in state:
            result['output'] = state['output']
            message.setdefault('tool_results', []).append(result)
        elif state.get('status') == 'error':
            result['error'] = state.get('error')
            message.setdefault('tool_results', []).append(result)
    elif part_type == 'file':
        message.setdefault('attachments', []).append({
            key: part_data.get(key) for key in ('filename', 'mime', 'url')
        })
    elif part_type not in SKIP_PART_TYPES and text:
        message.setdefault('_content_parts', []).append(text)


def finalize_message(message):
    """Join message text and reasoning parts in database order."""
    message['content'] = '\n'.join(message.pop('_content_parts', []))
    reasoning = message.pop('_reasoning_parts', [])
    if reasoning:
        message['reasoning'] = '\n'.join(reasoning)
    return message


def _optional_rows(conn, table, fields, session_id, order=None):
    columns = _columns(conn, table)
    if 'session_id' not in columns:
        return []
    selected = ', '.join(field if field in columns else 'NULL AS ' + field
                         for field in fields)
    query = 'SELECT ' + selected + ' FROM ' + table + ' WHERE session_id = ?'
    if order in columns:
        query += ' ORDER BY ' + order
    return conn.execute(query, (session_id,)).fetchall()


def extract_session(conn, session_row, db_path, warnings=None):
    """Build one conversation from a session and its ordered messages and parts."""
    if warnings is None:
        warnings = Counter()
    messages = []
    all_content = []
    rows = conn.execute(
        'SELECT id, time_created, data FROM message WHERE session_id = ? '
        'ORDER BY time_created, id', (session_row['id'],)).fetchall()
    for row in rows:
        data = _object(row['data'], warnings, 'messages')
        if data is None:
            continue
        created = data.get('time')
        if not isinstance(created, dict):
            created = {}
        role = data.get('role', 'assistant')
        if not isinstance(role, str):
            warnings['message fields'] += 1
            role = 'assistant'
        message = {'role': role, 'content': '',
                   'timestamp': created.get('created', row['time_created'])}
        for field in MESSAGE_FIELDS:
            if data.get(field) is not None:
                message[field] = data[field]
        if 'parentID' in data:
            message['parent_id'] = data['parentID']
        for part_row in conn.execute(
                'SELECT data FROM part WHERE session_id = ? AND message_id = ? '
                'ORDER BY time_created, id', (session_row['id'], row['id'])):
            part = _object(part_row[0], warnings, 'parts')
            if part is not None:
                apply_part(part, message, all_content, warnings)
        messages.append(finalize_message(message))
    if not messages:
        return None

    session = dict(session_row)
    conversation = {'messages': messages, 'source': 'zcode',
                    'session_id': session['id'], 'db_path': str(db_path)}
    fields = {'parent_session_id': 'parent_id', 'created_at': 'time_created',
              'updated_at': 'time_updated'}
    for field in ('task_type', 'slug', 'directory', 'title', 'title_source',
                  'version', 'share_url', 'time_archived'):
        fields[field] = field
    for field, column in fields.items():
        conversation[field] = session.get(column)

    goals = _optional_rows(conn, 'session_target',
                           ('objective', 'status', 'token_budget', 'tokens_used',
                            'time_used_seconds'), session['id'])
    if goals:
        conversation['goal'] = dict(goals[0])
    todos = _optional_rows(conn, 'todo', ('content', 'status', 'priority'),
                           session['id'], order='position')
    if todos:
        conversation['todos'] = [dict(todo) for todo in todos]
    return conversation


def extract_conversations(db_path=None):
    """Read conversations from one database without changing its main file."""
    db_path = Path(db_path) if db_path is not None else DB_PATH
    if not db_path.is_file():
        return None, []
    warnings = Counter()
    conversations = []
    with open_snapshot(db_path) as conn:
        _check_schema(conn)
        sessions = conn.execute(
            'SELECT * FROM session ORDER BY time_created, id').fetchall()
        print('Found {} sessions'.format(len(sessions)))
        for session in sessions:
            conversation = extract_session(conn, session, db_path, warnings)
            if conversation:
                conversations.append(conversation)
    for category, count in sorted(warnings.items()):
        print('Warning: malformed {}: {}'.format(category, count), file=sys.stderr)
    return db_path, conversations


def main():
    """Extract the selected database into a timestamped JSONL file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=DB_PATH,
                        help='ZCode SQLite database path')
    args = parser.parse_args()
    try:
        db_path, conversations = extract_conversations(args.db)
    except (sqlite3.Error, OSError, ValueError):
        print('Error: cannot read the ZCode database. Check its schema and permissions.',
              file=sys.stderr)
        return 1
    if db_path is None:
        print('Error: no ZCode database found. Use --db to select a database.',
              file=sys.stderr)
        return 1
    print('Total conversations extracted: {}'.format(len(conversations)))
    if not conversations:
        return 0
    print('Total messages: {}'.format(sum(len(c['messages']) for c in conversations)))
    output_dir = Path('extracted_data')
    try:
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / ('zcode_conversations_' + timestamp + '.jsonl')
        with output_file.open('x', encoding='utf-8') as stream:
            for conversation in conversations:
                stream.write(json_line(conversation) + '\n')
    except OSError:
        print('Error: cannot write the ZCode export.', file=sys.stderr)
        return 1
    print('Saved to: {}'.format(output_file))
    print('Corpus contains private code and paths. Filter it before sharing.',
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())

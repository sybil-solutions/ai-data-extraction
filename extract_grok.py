#!/usr/bin/env python3
"""
Extract ALL Grok Build (xAI terminal coding agent) session data.

Grok Build stores sessions under:
  ~/.grok/sessions/<encoded-cwd>/<session-id>/
(or $GROK_HOME/sessions/<encoded-cwd>/<session-id>/ when GROK_HOME is set).

Each session directory may contain:
  - summary.json            (title, summary, recap, model, timestamps, parent_session_id)
  - updates.jsonl           (ACP session update stream: messages, thoughts, tool calls, file edits)
  - chat_history.jsonl      (raw chat messages sent to the model)
  - system_prompt.txt       (rendered system prompt)
  - prompt_context.json     (system prompt context inputs)
  - tool_definitions.json   (function tool schemas)
  - plan.json               (TODO / task list state)
  - rewind_points.jsonl     (rewind checkpoints)
  - signals.json            (token usage, turn/tool counters)
  - feedback.jsonl          (user feedback and ratings)
  - subagents/              (per-subagent meta.json linking child sessions)
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote


def find_session_roots():
    """Return existing Grok Build session root directories."""
    roots = []
    grok_home = os.environ.get("GROK_HOME", "").strip()
    if grok_home:
        roots.append(Path(grok_home).expanduser() / "sessions")
    roots.append(Path.home() / ".grok" / "sessions")
    seen = []
    for r in roots:
        if r.exists() and r not in seen:
            seen.append(r)
    return seen


def _read_json(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _read_jsonl(path):
    if not path.is_file():
        return []
    rows = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
    except Exception:
        pass
    return rows


def _iso(ts):
    if isinstance(ts, (int, float)):
        scale = 1000.0 if ts > 1e11 else 1.0
        return datetime.fromtimestamp(ts / scale, timezone.utc).isoformat().replace("+00:00", "Z")
    return ts


def resolve_project_path(group_dir, summary=None):
    """Resolve the workspace path from .cwd, summary.json, or URL-encoded group name."""
    cwd_file = group_dir / ".cwd"
    if cwd_file.is_file():
        try:
            val = cwd_file.read_text(encoding="utf-8", errors="replace").strip()
            if val:
                return val
        except Exception:
            pass
    if isinstance(summary, dict):
        for key in ("cwd", "working_directory", "workingDirectory", "project_path", "projectPath"):
            if isinstance(summary.get(key), str) and summary[key].strip():
                return summary[key].strip()
    return unquote(group_dir.name)


def _extract_text_and_parts(content):
    if isinstance(content, str):
        return content, [], [], []
    if isinstance(content, dict):
        content = [content]
    if not isinstance(content, list):
        return "", [], [], []

    texts, thoughts, tool_calls, tool_results = [], [], [], []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        ptype = part.get("type") or part.get("kind") or ""
        if ptype in ("text", "input_text", "output_text") and isinstance(part.get("text"), str):
            texts.append(part["text"])
        elif ptype in ("thinking", "reasoning", "thought", "agent_thought"):
            t = part.get("thinking") or part.get("reasoning") or part.get("text") or ""
            if isinstance(t, str) and t:
                thoughts.append(t)
        elif ptype in ("tool_use", "tool_call", "toolCall", "function_call"):
            args = part.get("arguments") if "arguments" in part else part.get("input", part.get("rawInput"))
            if isinstance(args, (dict, list)):
                args_str = json.dumps(args, ensure_ascii=False)
            else:
                args_str = str(args or "")
            tool_calls.append({
                "id": part.get("id") or part.get("toolCallId") or part.get("call_id"),
                "type": "function",
                "function": {
                    "name": part.get("name") or (part.get("function") or {}).get("name"),
                    "arguments": args_str,
                },
            })
        elif ptype in ("tool_result", "toolResult", "function_call_output"):
            out = part.get("content") if "content" in part else part.get("output", part.get("rawOutput", ""))
            if isinstance(out, (dict, list)):
                out_str = json.dumps(out, ensure_ascii=False)
            else:
                out_str = str(out or "")
            tool_results.append({
                "tool_call_id": part.get("tool_use_id") or part.get("toolCallId") or part.get("call_id") or part.get("id"),
                "name": part.get("name") or part.get("toolName"),
                "content": out_str,
                "is_error": bool(part.get("is_error") or part.get("isError")),
            })
    return "\n".join(t for t in texts if t), thoughts, tool_calls, tool_results


def _normalize_chat_entry(entry):
    msg = entry.get("message") if isinstance(entry.get("message"), dict) else entry
    role = msg.get("role") or entry.get("role")
    if not role:
        return []
    text, thoughts, c_tools, c_results = _extract_text_and_parts(msg.get("content"))
    ts = _iso(msg.get("timestamp") or entry.get("timestamp") or entry.get("created_at"))
    model = msg.get("model") or entry.get("model")
    usage = msg.get("usage") or entry.get("usage")

    if isinstance(msg.get("reasoning"), str) and msg["reasoning"]:
        thoughts.insert(0, msg["reasoning"])
    if isinstance(msg.get("thinking"), str) and msg["thinking"]:
        thoughts.insert(0, msg["thinking"])

    raw_tc = msg.get("tool_calls") or msg.get("toolCalls") or []
    for tc in raw_tc if isinstance(raw_tc, list) else []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        args = fn.get("arguments") if "arguments" in fn else tc.get("arguments", tc.get("input"))
        if isinstance(args, (dict, list)):
            args = json.dumps(args, ensure_ascii=False)
        c_tools.append({
            "id": tc.get("id") or tc.get("toolCallId"),
            "type": "function",
            "function": {
                "name": fn.get("name") or tc.get("name"),
                "arguments": str(args or ""),
            },
        })

    normalized = []
    if role in ("tool", "toolResult") or (msg.get("tool_call_id") or msg.get("toolCallId")):
        normalized.append({
            "role": "tool",
            "content": text,
            "tool_call_id": msg.get("tool_call_id") or msg.get("toolCallId") or entry.get("id"),
            **({"name": msg.get("name") or msg.get("toolName")} if (msg.get("name") or msg.get("toolName")) else {}),
            **({"timestamp": ts} if ts else {}),
        })
        return normalized

    rec = {"role": role, "content": text}
    if thoughts:
        rec["reasoning"] = "\n\n".join(thoughts)
    if c_tools:
        rec["tool_calls"] = c_tools
    if model:
        rec["model"] = model
    if isinstance(usage, dict):
        rec["usage"] = usage
    if ts:
        rec["timestamp"] = ts
    if rec.get("content") or rec.get("reasoning") or rec.get("tool_calls"):
        normalized.append(rec)

    for tr in c_results:
        t_rec = {
            "role": "tool",
            "content": tr["content"],
            "tool_call_id": tr["tool_call_id"],
        }
        if tr.get("name"):
            t_rec["name"] = tr["name"]
        if tr.get("is_error"):
            t_rec["is_error"] = True
        if ts:
            t_rec["timestamp"] = ts
        normalized.append(t_rec)

    return normalized


def _parse_updates(rows):
    """Parse ACP session update stream (updates.jsonl) into messages and file edits."""
    messages = []
    file_edits = []
    models = set()

    for row in rows:
        update = row.get("update") if isinstance(row.get("update"), dict) else row
        utype = (
            update.get("sessionUpdate")
            or update.get("type")
            or update.get("kind")
            or row.get("type")
            or ""
        )
        ts = _iso(update.get("timestamp") or row.get("timestamp") or row.get("created_at"))
        model = update.get("model") or row.get("model")
        if isinstance(model, str) and model:
            models.add(model)

        if utype in ("user_message", "user_message_chunk", "prompt"):
            text, _, _, _ = _extract_text_and_parts(update.get("content", update.get("text", "")))
            if text:
                msg = {"role": "user", "content": text}
                if ts:
                    msg["timestamp"] = ts
                messages.append(msg)
        elif utype in ("agent_message", "agent_message_chunk", "assistant_message"):
            text, thoughts, tcs, _ = _extract_text_and_parts(update.get("content", update.get("text", "")))
            if text or thoughts or tcs:
                msg = {"role": "assistant", "content": text}
                if thoughts:
                    msg["reasoning"] = "\n\n".join(thoughts)
                if tcs:
                    msg["tool_calls"] = tcs
                if model:
                    msg["model"] = model
                if ts:
                    msg["timestamp"] = ts
                messages.append(msg)
        elif utype in ("agent_thought", "agent_thought_chunk", "thinking", "thought"):
            text, _, _, _ = _extract_text_and_parts(update.get("content", update.get("text", update.get("thinking", ""))))
            if text:
                if messages and messages[-1]["role"] == "assistant" and not messages[-1].get("content"):
                    prev = messages[-1].get("reasoning", "")
                    messages[-1]["reasoning"] = f"{prev}\n\n{text}".strip() if prev else text
                else:
                    msg = {"role": "assistant", "content": "", "reasoning": text}
                    if model:
                        msg["model"] = model
                    if ts:
                        msg["timestamp"] = ts
                    messages.append(msg)
        elif utype in ("tool_call", "tool_call_update", "tool_use"):
            tc_id = update.get("toolCallId") or update.get("id")
            name = update.get("name") or update.get("toolName") or update.get("title")
            raw_in = update.get("rawInput") if "rawInput" in update else update.get("input", update.get("arguments"))
            raw_out = update.get("rawOutput") if "rawOutput" in update else update.get("output", update.get("result"))
            locs = update.get("locations") or update.get("files") or []
            for loc in locs if isinstance(locs, list) else []:
                path_val = loc.get("path") if isinstance(loc, dict) else loc if isinstance(loc, str) else None
                if path_val and path_val not in file_edits:
                    file_edits.append(path_val)
            for key in ("path", "file_path", "filePath"):
                if isinstance(raw_in, dict) and isinstance(raw_in.get(key), str) and raw_in[key] not in file_edits:
                    file_edits.append(raw_in[key])

            if utype != "tool_call_update" or raw_in is not None:
                args_str = json.dumps(raw_in, ensure_ascii=False) if isinstance(raw_in, (dict, list)) else str(raw_in or "")
                tc_entry = {
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": name, "arguments": args_str},
                }
                if update.get("status"):
                    tc_entry["status"] = update["status"]
                if locs:
                    tc_entry["locations"] = locs
                msg = {"role": "assistant", "content": "", "tool_calls": [tc_entry]}
                if model:
                    msg["model"] = model
                if ts:
                    msg["timestamp"] = ts
                messages.append(msg)

            if raw_out is not None:
                out_str = json.dumps(raw_out, ensure_ascii=False) if isinstance(raw_out, (dict, list)) else str(raw_out)
                t_msg = {"role": "tool", "content": out_str, "tool_call_id": tc_id}
                if name:
                    t_msg["name"] = name
                if update.get("status") in ("failed", "error") or update.get("isError"):
                    t_msg["is_error"] = True
                if ts:
                    t_msg["timestamp"] = ts
                messages.append(t_msg)
        elif "role" in update or "message" in update:
            messages.extend(_normalize_chat_entry(update))

    return messages, file_edits, sorted(models)


def _extract_subagents(session_dir):
    sub_dir = session_dir / "subagents"
    if not sub_dir.is_dir():
        return []
    subagents = []
    for meta_path in sorted(sub_dir.rglob("*.json")):
        data = _read_json(meta_path)
        if isinstance(data, dict):
            subagents.append(data)
    return subagents


def extract_session(session_dir, group_dir=None):
    """Extract a single Grok Build session directory into a normalized conversation dict."""
    session_dir = Path(session_dir)
    group_dir = Path(group_dir) if group_dir else session_dir.parent

    summary = _read_json(session_dir / "summary.json") or {}
    signals = _read_json(session_dir / "signals.json") or {}
    plan = _read_json(session_dir / "plan.json")
    prompt_context = _read_json(session_dir / "prompt_context.json")
    tool_defs = _read_json(session_dir / "tool_definitions.json")
    rewind_points = _read_jsonl(session_dir / "rewind_points.jsonl")
    feedback = _read_jsonl(session_dir / "feedback.jsonl")
    subagents = _extract_subagents(session_dir)

    sys_prompt_path = session_dir / "system_prompt.txt"
    system_prompt = (
        sys_prompt_path.read_text(encoding="utf-8", errors="replace").strip()
        if sys_prompt_path.is_file()
        else None
    )

    chat_rows = _read_jsonl(session_dir / "chat_history.jsonl")
    chat_messages = []
    for r in chat_rows:
        chat_messages.extend(_normalize_chat_entry(r))

    update_rows = _read_jsonl(session_dir / "updates.jsonl")
    update_messages, file_edits, update_models = _parse_updates(update_rows)

    messages = chat_messages if len(chat_messages) >= len(update_messages) and chat_messages else update_messages
    if not messages or not any(m.get("role") == "assistant" for m in messages):
        return None

    for m in messages:
        for tc in m.get("tool_calls", []):
            args_raw = (tc.get("function") or {}).get("arguments") or ""
            try:
                parsed = json.loads(args_raw) if isinstance(args_raw, str) and args_raw.startswith("{") else {}
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                for key in ("path", "file_path", "filePath", "target_file"):
                    if isinstance(parsed.get(key), str) and parsed[key] not in file_edits:
                        file_edits.append(parsed[key])

    models = set(update_models)
    for m in messages:
        if isinstance(m.get("model"), str) and m["model"]:
            models.add(m["model"])
    summary_model = summary.get("model") or summary.get("model_id") or summary.get("modelId")
    if isinstance(summary_model, str) and summary_model:
        models.add(summary_model)

    session_id = (
        summary.get("session_id")
        or summary.get("sessionId")
        or summary.get("id")
        or session_dir.name
    )
    title = summary.get("title") or summary.get("manual_title") or summary.get("generated_title")
    parent_id = (
        summary.get("parent_session_id")
        or summary.get("parentSessionId")
        or summary.get("parent_id")
        or summary.get("parentId")
    )
    created_at = _iso(summary.get("created_at") or summary.get("createdAt") or messages[0].get("timestamp"))
    updated_at = _iso(summary.get("updated_at") or summary.get("updatedAt") or messages[-1].get("timestamp"))

    conv = {
        "messages": messages,
        "source": "grok",
        "session_id": session_id,
        "project_path": resolve_project_path(group_dir, summary),
        "created_at": created_at,
        "updated_at": updated_at,
        "models": sorted(models),
    }
    if summary_model:
        conv["model"] = summary_model
    if title:
        conv["title"] = title
    if summary.get("summary") or summary.get("recap") or summary.get("last_turn_summary"):
        conv["summary"] = {
            k: summary[k]
            for k in ("summary", "recap", "last_turn_summary", "lastTurnSummary", "sessionRecap")
            if k in summary
        }
    if parent_id:
        conv["parent_session_id"] = parent_id
    if system_prompt:
        conv["system_prompt"] = system_prompt
    if prompt_context:
        conv["prompt_context"] = prompt_context
    if isinstance(tool_defs, list) and tool_defs:
        conv["tools"] = [
            t.get("name") or (t.get("function") or {}).get("name")
            for t in tool_defs
            if isinstance(t, dict) and (t.get("name") or (t.get("function") or {}).get("name"))
        ]
    if plan:
        conv["plan"] = plan
    if signals:
        conv["signals"] = signals
        usage = signals.get("token_usage") or signals.get("tokenUsage") or signals.get("usage")
        if usage:
            conv["token_usage"] = usage
    if rewind_points:
        conv["rewind_points"] = rewind_points
    if feedback:
        conv["feedback"] = feedback
    if subagents:
        conv["subagents"] = subagents
    if file_edits:
        conv["files_touched"] = file_edits

    return conv


def discover_sessions(roots=None):
    """Yield (session_dir, group_dir) pairs across all Grok session roots."""
    roots = roots if roots is not None else find_session_roots()
    seen = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for marker in ("summary.json", "updates.jsonl", "chat_history.jsonl"):
            for fpath in sorted(root.rglob(marker)):
                sdir = fpath.parent
                if sdir.name == "subagents" or "subagents" in sdir.parts:
                    continue
                if sdir not in seen:
                    seen.add(sdir)
                    yield sdir, sdir.parent


def main():
    print("=" * 80)
    print("GROK BUILD SESSION EXTRACTION (~/.grok/sessions)")
    print("=" * 80)

    roots = find_session_roots()
    if not roots:
        print(f"No Grok Build sessions found (checked {Path.home() / '.grok' / 'sessions'}).")
        return

    all_convs = []
    for sdir, gdir in discover_sessions(roots):
        conv = extract_session(sdir, gdir)
        if conv:
            all_convs.append(conv)

    if not all_convs:
        print("No complete Grok Build conversations found.")
        return

    total_msgs = sum(len(c["messages"]) for c in all_convs)
    with_tools = sum(1 for c in all_convs if any(m.get("tool_calls") or m["role"] == "tool" for m in c["messages"]))
    with_reasoning = sum(1 for c in all_convs if any(m.get("reasoning") for m in c["messages"]))

    print(f"Total conversations: {len(all_convs):,}")
    print(f"Total messages: {total_msgs:,}")
    print(f"With tool calls/results: {with_tools:,}")
    print(f"With reasoning: {with_reasoning:,}")

    out_dir = Path("extracted_data")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"grok_conversations_{ts}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for c in all_convs:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    size = out_file.stat().st_size / 1024 / 1024
    print(f"Saved: {out_file} ({size:.2f} MB)")


if __name__ == "__main__":
    main()

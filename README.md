# AI Coding Assistant Training Data Extraction Toolkit

Complete toolkit to extract ALL chat, agent, and code context data from AI coding assistants for machine learning training.

## 🎯 What This Does

Automatically discovers and extracts **complete conversation history** including:
- ✅ User messages & AI responses
- ✅ Code context (file paths, line numbers, snippets)
- ✅ Code diffs and suggested edits
- ✅ Multi-file contexts
- ✅ Tool use and execution results
- ✅ Timestamps and metadata

Pi and OMP session exports use one shared parser. The default follows the active
branch; `python3 extract_pi.py --all-branches` and `python3 extract_omp.py --all-branches`
export separate leaf conversations with their ancestry and branch IDs. String
answers, custom context, reasoning, tool-call IDs, model changes, advisor/subagent
sessions and branch summaries are preserved. OMP also supports `--prompt-history`
for a separate read-only SQLite snapshot, including committed WAL rows.

`extract_droid.py` reads Factory/Droid sessions and settings under `~/.factory/sessions`.
The aggregate script includes all three. The parser consolidation carries the
Pi/OMP work from PR #26, Joshua Warren's OMP coverage from #17 and Umang Bhalla's
Droid contribution from #7, with regression fixes and attribution.

## 📦 Included Scripts

### 1. `extract_claude_code.py`
Extracts from Claude Code / Claude Desktop
- **Searches**: `~/.claude`, `~/.claude-code`, `~/.claude-local`, `~/.claude-m2`, `~/.claude-zai`
- **Formats**: JSONL session files
- **Includes**: Messages, tool use, file contexts, diffs

### 2. `extract_codex.py`
Extracts from Codex (if installed)
- **Searches**: `~/.codex`, `~/.codex-local`
- **Formats**: Rollout JSONL files
- **Includes**: User/agent messages, tool results, diffs

### 3. `extract_cursor.py`
Extracts from Cursor (Chat + Composer + Agent) - ALL VERSIONS
- **Searches**: `~/Library/Application Support/Cursor` (macOS) or equivalent
- **Formats**: SQLite databases (`state.vscdb`, `cursorDiskKV`)
- **Handles**:
  - Old Chat mode (workspace storage)
  - Composer inline storage (v1.x - messages in composerData array)
  - Composer separate storage (v1.x-v2.0 transition - messages in bubbleId keys)
  - Latest Composer/Agent (v2.0+)
- **Includes**:
  - Code context, selections, diffs
  - Suggested edits and code blocks
  - Tool results and execution outputs

### 4. `extract_trae.py`
Extracts from Trae
- **Searches**: `~/.trae`, `~/Library/Application Support/Trae`
- **Formats**: JSONL and SQLite databases
- **Includes**: Chat, agent data, tool use, diffs

### 5. `extract_windsurf.py`
Extracts from Windsurf
- **Searches**: `~/Library/Application Support/Windsurf` or equivalent
- **Formats**: SQLite databases (VSCode-like format)
- **Includes**: Chat, agent/flow conversations, code context

### 6. `extract_continue.py`
Extracts from Continue AI Assistant
- **Searches**: `~/.continue/sessions/`
- **Formats**: JSON session files
- **Includes**:
  - User/assistant messages
  - Tool calls and results
  - Reasoning blocks
  - Context items
  - Workspace information

### 7. `extract_gemini.py`
Extracts from Google Gemini CLI
- **Searches**: `~/.gemini/tmp/[hash]/chats/`
- **Formats**: JSON session files
- **Includes**:
  - User/assistant messages
  - Thoughts (reasoning steps with timestamps)
  - Token usage breakdown
  - Model information
  - Project hash and workspace linking

### 8. `extract_opencode.py`
Extracts from OpenCode (CLI + Desktop)
- **Searches**: 
  - CLI: `~/.local/share/opencode/` (Linux), `~/Library/Application Support/opencode` (macOS)
  - Desktop: `~/.local/share/ai.opencode.app` (Linux), `~/Library/Application Support/ai.opencode.app` (macOS)
- **Formats**: SQLite (`opencode.db`), JSON files (sessions/messages/parts), and Tauri .dat files (desktop)
- **Includes**:
  - User/assistant messages with full conversation hierarchy
  - Tool calls and tool results
  - Code blocks and text content
  - Token usage and cost tracking
  - Model and provider information
  - Agent mode and session metadata
  - Project directory and version info
  - Parent/child session relationships
- **Handles**:
  - newer OpenCode CLI installs that store conversations in `opencode.db`
  - legacy JSON storage layouts under `storage/message`, `storage/part`, and `storage/session`
  - sidecar metadata from `storage/session_diff`, `storage/directory-readme`, `storage/agent-usage-reminder`, and `storage/rules-injector`

### 9. `extract_cursor_cli.py`
Extracts from the `cursor-agent` terminal CLI (the Composer/Agent history that the GUI
extractor in `extract_cursor.py` does not cover)
- **Searches**: `~/.cursor/chats/<chatId>/<agentId>/store.db` (all platforms)
- **Formats**: content-addressed SQLite blob store
  - `blobs` table: `id` (sha256 hex) → `data`; message blobs are JSON (`{role, content, id, ...}`),
    tree nodes are protobuf-framed lists of 32-byte child blob-id refs
  - `meta` table: hex-encoded JSON with `agentId`, `latestRootBlobId`, `name`, `mode`, `createdAt`
- **Includes**:
  - Ordered messages reconstructed by DFS-walking refs from `latestRootBlobId`
  - System/user/assistant/tool turns with full content
  - Chat/agent ids, title, mode, created-at, code-context and diff flags

## 🚀 Quick Start

### Installation

```bash
# No dependencies required - uses Python 3 standard library
python3 --version  # Ensure Python 3.6+ is installed
```

### Basic Usage

```bash
# Extract from Claude Code
python3 extract_claude_code.py

# Extract from Cursor
python3 extract_cursor.py

# Extract from Codex
python3 extract_codex.py

# Extract from Trae
python3 extract_trae.py

# Extract from Windsurf
python3 extract_windsurf.py

# Extract from Continue
python3 extract_continue.py

# Extract from Gemini CLI
python3 extract_gemini.py

# Extract from OpenCode
python3 extract_opencode.py

# Extract from Cursor CLI (cursor-agent)
python3 extract_cursor_cli.py

# Extract from Grok Build
python3 extract_grok.py

# Extract from ALL tools at once
./extract_all.sh
```

### Output

All scripts create an `extracted_data/` directory with timestamped JSONL files:

```
extracted_data/
├── claude_code_conversations_20250116_143022.jsonl
├── cursor_complete_20250116_143045.jsonl
├── gemini_conversations_20250116_143145.jsonl
├── codex_conversations_20250116_143102.jsonl
├── trae_conversations_20250116_143115.jsonl
├── windsurf_conversations_20250116_143130.jsonl
├── continue_conversations_20250116_143145.jsonl
└── opencode_conversations_20250116_143200.jsonl
```

## 📊 Output Format

Each conversation is a single JSON line in JSONL format:

```json
{
  "messages": [
    {
      "role": "user",
      "content": "How do I fix this TypeScript error?",
      "code_context": [
        {
          "file": "/Users/user/project/src/index.ts",
          "code": "const x: string = 123;",
          "range": {
            "selectionStartLineNumber": 10,
            "positionLineNumber": 10
          }
        }
      ],
      "timestamp": "2025-01-16T14:30:22.123Z"
    },
    {
      "role": "assistant",
      "content": "The error occurs because you're assigning a number to a string type...",
      "suggested_diffs": [...],
      "model": "claude-sonnet-4-5",
      "timestamp": "2025-01-16T14:30:25.456Z"
    }
  ],
  "source": "cursor-composer",
  "name": "TypeScript Type Error Fix",
  "created_at": 1705414222000
}
```

## 🔍 How It Works

### Auto-Discovery Process

Each script follows this pattern:

1. **Detect Operating System** (macOS, Linux, Windows)
2. **Search Common Locations**:
   - macOS: `~/Library/Application Support`, `~/.config`, `~/`
   - Linux: `~/.config`, `~/.local/share`, `~/`
   - Windows: `%APPDATA%`, `%LOCALAPPDATA%`, `~/`
3. **Find All Installations** of the target tool
4. **Scan Storage Locations**:
   - SQLite databases (`.vscdb`, `.db`)
   - JSONL session files
   - Project-specific directories
5. **Extract Complete Data** including context and diffs
6. **Save to Organized JSONL** with timestamps

### Storage Formats Handled

#### Claude Code / Codex
- **Format**: JSONL files (one event per line)
- **Location**: `~/.claude/projects/[project]/[session].jsonl`
- **Structure**: Event-based with type markers

#### Cursor (v0.43 - v2.0+)
- **Format**: SQLite databases
- **Locations**:
  - Workspace: `~/Library/Application Support/Cursor/User/workspaceStorage/[hash]/state.vscdb`
  - Global: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`
- **Tables**: `ItemTable` (Chat), `cursorDiskKV` (Composer/Agent)
- **Storage Evolution**:
  - **v0.x - v1.x**: Chat mode in workspace `ItemTable`
  - **v1.x**: Composer inline (messages in `composerData.conversation[]`)
  - **v1.x - v2.0 transition**: Composer separate (messages in `bubbleId:{composer}:{bubble}` keys)
  - **v2.0+**: Latest format with enhanced metadata
- **Keys**:
  - `workbench.panel.aichat.view.aichat.chatdata` (Chat mode)
  - `composerData:{uuid}` (Composer metadata + conversation)
  - `bubbleId:{composer}:{bubble}` (Individual messages - transitional format)
  - `codeBlockDiff:{id}` (Code block diffs)

#### Trae / Windsurf
- **Format**: Hybrid (JSONL + SQLite)
- **Location**: Similar to VSCode/Cursor structure
- **Structure**: VSCode extension data format

## 🎓 Understanding the Data

### Message Roles
- `user`: Human developer messages
- `assistant`: AI assistant responses

### Code Context Fields
- `code_context`: File selections and code snippets
- `suggested_diffs`: AI-proposed code changes
- `tool_use`: Code execution, file operations
- `tool_results`: Execution outputs, diffs applied
- `diff_histories`: Full edit history

### Metadata Fields
- `source`: Which tool (e.g., "cursor-composer", "claude-code")
- `session_id`/`composer_id`: Unique conversation ID
- `project_path`: Working directory
- `timestamp`: Message time
- `model`: AI model used (if available)

## 🔧 Advanced Usage

### Merge All Extractions

```bash
# Combine all JSONL files
cat extracted_data/*.jsonl > all_conversations.jsonl

# Count total conversations
wc -l all_conversations.jsonl

# Count by source
grep -o '"source":"[^"]*"' all_conversations.jsonl | sort | uniq -c
```

### Create Agent Skills from a corpus

`corpus_to_skills.py` samples extracted conversations and asks an
OpenAI-compatible chat-completions model to synthesize reusable
[Agent Skills](https://agentskills.io/specification). Each result is written as
`<skill-name>/SKILL.md` with validated `name` and `description` metadata.

The command is local-first: unless `OPENAI_BASE_URL` is set, it connects to
`http://127.0.0.1:8000/v1`. Point it at a locally served model and a filtered
corpus:

```bash
python3 corpus_to_skills.py filtered_data \
  --model your-local-model \
  --skills 5 \
  --output-dir generated_skills
```

You can also set `SKILLS_MODEL` instead of passing `--model`. The script uses
only Python's standard library, samples across the corpus with a configurable
character budget, treats corpus content as untrusted data, validates the model's
JSON response, and refuses to overwrite existing skills unless `--overwrite`
is passed.

Review every generated skill before installing it. Filter the extracted corpus
first, especially before explicitly configuring a remote API endpoint; model
output can still repeat sensitive source material despite prompt-level guards.

### Filter by Date

```python
import json
from datetime import datetime

with open('extracted_data/cursor_complete_20250116.jsonl') as f:
    for line in f:
        conv = json.loads(line)
        created = conv.get('created_at', 0)
        if created > 1704067200000:  # After Jan 1, 2024
            print(json.dumps(conv))
```

### Extract Only Conversations with Diffs

```python
import json

with open('extracted_data/cursor_complete.jsonl') as f:
    for line in f:
        conv = json.loads(line)
        if any('suggested_diffs' in m or 'diff_histories' in m
               for m in conv['messages']):
            print(json.dumps(conv))
```

## 📋 Data Quality

### What Gets Extracted

✅ **Complete Conversations**:
- Both user prompts AND AI responses
- Multi-turn dialogues
- Full conversation context

✅ **Code Context**:
- File paths and names
- Selected code snippets
- Line number ranges
- Multi-file selections

✅ **Diffs and Edits**:
- Suggested code changes
- Applied diffs
- Edit histories
- File modifications

✅ **Metadata**:
- Timestamps
- Project paths
- Model information
- Conversation names

### What Might Be Missing

⚠️ **Partial Data**:
- Conversations without AI responses (user-only)
- Deleted or archived sessions
- Corrupted database entries

⚠️ **Privacy Considerations**:
- May include proprietary code
- May include API keys/secrets
- May include personal file paths

## 🛡️ Privacy & Security

### Filter a corpus with OpenAI Privacy Filter

The optional `filter_privacy.py` command runs the official
[`openai/privacy-filter`](https://huggingface.co/openai/privacy-filter) model
locally and replaces detected spans with typed placeholders such as
`<PRIVATE_EMAIL>` and `<SECRET>`. It recursively filters every string value, so
messages, code, tool output, diffs, and path metadata are all covered while the
JSON structure stays intact.

The privacy filter requires Python 3.10+ and downloads the model weights on its
first run (about 2.8 GB). Install the pinned official OpenAI runtime separately:

```bash
python3 -m pip install -r requirements-privacy-filter.txt
```

Filter individual JSONL files or a whole extraction directory:

```bash
python3 filter_privacy.py extracted_data --output-dir filtered_data

# Use CUDA when available
python3 filter_privacy.py extracted_data --output-dir filtered_data --device cuda
```

Inputs are never modified. Existing outputs are refused unless `--overwrite`
is supplied. The unfiltered text stays local: the runtime downloads the model
from Hugging Face and performs inference on the selected CPU or CUDA device.

Privacy Filter is a data-minimization aid, not an anonymization or compliance
guarantee. Review filtered output and combine it with secret scanning and your
organization's privacy controls before sharing or training.

### Before Using Extracted Data

1. **Scan for Secrets**:
```bash
pip install detect-secrets
detect-secrets scan extracted_data/*.jsonl
```

2. **Review Sensitive Data**:
- Check for API keys, passwords, tokens
- Verify no proprietary code exposed
- Sanitize file paths if needed

3. **Storage**:
- Keep on encrypted drives
- Don't commit to public repositories
- Secure backups recommended

## 🎯 Training Use Cases

### Direct Fine-Tuning

```python
from datasets import load_dataset

dataset = load_dataset(
    'json',
    data_files='extracted_data/*.jsonl',
    split='train'
)

# Filter complete conversations
dataset = dataset.filter(
    lambda x: any(m['role'] == 'assistant' for m in x['messages'])
)
```

### With Unsloth

```python
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    "unsloth/qwen2.5-coder-7b-instruct",
    max_seq_length=4096,
    load_in_4bit=True,
)

def format_chat(example):
    return {
        'text': tokenizer.apply_chat_template(
            example['messages'],
            tokenize=False
        )
    }

dataset = dataset.map(format_chat)
```

## 🐛 Troubleshooting

### No installations found

**Problem**: Script reports "No installations found"

**Solutions**:
1. Check if the tool is actually installed
2. Verify installation location manually
3. Add custom path to script:
```python
# Add to find_XXX_installations() function
locations.append(Path("/custom/path/to/tool"))
```

### Empty extracted_data directory

**Problem**: Extraction completes but no data found

**Solutions**:
1. Verify you've actually used the tool and have chat history
2. Check if data is in a non-standard location
3. Look for database files manually:
```bash
find ~ -name "*.vscdb" -o -name "*.db" 2>/dev/null
```

Cursor database paths containing `#`, `?`, or literal percent escapes are supported; filesystem paths are URI-encoded before opening them read-only.

### Database locked errors

**Problem**: SQLite database is locked

**Solutions**:
1. Close the AI tool before running extraction
2. Use read-only mode:
```python
conn = sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True)
```

### Permission denied

**Problem**: Cannot read certain files

**Solutions**:
1. Run with appropriate permissions
2. Check file ownership
3. Copy databases to accessible location first

## 📚 Platform-Specific Notes

### macOS
- Uses `~/Library/Application Support` for most tools
- May need Full Disk Access for system directories
- SQLite databases typically in `~/Library/Application Support/[Tool]/User/`

### Linux
- Uses `~/.config` and `~/.local/share`
- Check `~/.local/state` for some tools
- May use `$XDG_CONFIG_HOME` if set

### Windows
- Uses `%APPDATA%` and `%LOCALAPPDATA%`
- Paths: `C:\Users\[User]\AppData\Roaming\[Tool]`
- May need admin privileges for Program Files

## 🔄 Version Compatibility

### Cursor
- ✅ v2 (0.43+): Composer/Agent in `cursorDiskKV`
- ✅ v1: Chat in workspace `ItemTable`
- ⚠️ Pre-v0.43: Different format, limited support

### Claude Code
- ✅ All versions with JSONL session files
- ✅ Project-based structure

### Codex
- ✅ Rollout JSONL format
- ✅ Time-based session organization

## 📈 Performance Tips

### Large Datasets
```bash
# Process in chunks
split -l 1000 all_conversations.jsonl chunk_

# Compress for storage
gzip extracted_data/*.jsonl
```

### Speed Optimization
```python
# Use multiprocessing for large scans
from multiprocessing import Pool

with Pool() as pool:
    results = pool.map(extract_from_db, db_files)
```

## 🤝 Contributing

Found a new storage format or tool? Contributions welcome!

1. Follow existing script structure
2. Add auto-discovery logic
3. Extract complete data (messages + context + diffs)
4. Output to organized JSONL
5. Update this README

## 📄 License

MIT License - Use freely for training ML models

## ⚠️ Disclaimer

This toolkit extracts YOUR OWN data from locally installed AI tools. Users are responsible for:
- Ensuring they have rights to extracted data
- Handling sensitive/proprietary information appropriately
- Complying with tool Terms of Service
- Scanning for secrets before sharing/training

---

**Generated**: January 16, 2025
**Status**: Production Ready
**Compatibility**: Python 3.6+, macOS/Linux/Windows

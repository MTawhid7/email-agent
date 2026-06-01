# Email Agent — Developer Guide

> For Claude Code and human contributors. Covers architecture, conventions, and how
> to make common changes. For deep technical detail, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## What this project is

A locally-run AI email assistant packaged as a native desktop app (`.app` / `.exe`).
It watches a Gmail inbox, generates AI replies via Gemini (with fallback to Groq / Grok /
Ollama), and surfaces them in a browser UI (Flask on `localhost:5001`) for human review
before any email is sent.

**Key constraint:** This is a _local_ desktop app — no cloud infrastructure, no public
endpoints, no Docker. Everything runs on the user's machine.

---

## Repository layout

```
core/                   Project-wide infrastructure (no domain deps)
  config.py             Settings frozen dataclass + JSON/env loaders
  exceptions.py         Typed exception hierarchy

ai/                     AI generation layer
  assembler.py          Pure function: greeting + body + signature → HTML
  prompts.py            All Gemini prompt builders
  generator.py          ReplyGenerator with LLM failover
  providers/
    base.py             LLMProvider ABC
    router.py           FallbackRouter — tries providers in order
    gemini_provider.py
    openai_compatible_provider.py   Works with Groq, Grok, OpenAI, Mistral
    ollama_provider.py

gmail/                  Gmail API + OAuth + IMAP IDLE
  auth.py               OAuth2 flow (allow_oauth_flow parameter)
  client.py             GmailClient — all Gmail API calls
  token_manager.py      Background proactive token refresh
  imap_watcher.py       IMAP IDLE watcher → sets wake_event on new mail

agent/                  Background processing
  daemon.py             Lifecycle: start/stop, IMAP, token, historyId (~300 lines)
  pipeline.py           Per-email AI processing: parse→skip→classify→generate→queue
  queue.py              ReviewQueue singleton (thread-safe in-memory dict)

observability/          Debugging and monitoring
  log_writer.py         AgentLogger — rotating structured JSON log file
  trace.py              ProcessingTrace + TraceStore (last 50 email traces)
  state.py              StateManager — persisted system health snapshot

contacts/               Contact profiles with tone preferences and teammate flags
history/                Per-contact interaction memory (last 10 sent replies)
email_parser/           Gmail thread → ParsedEmail dataclass + attachment reader
signature/              HTML + plain-text email signature builder
bulk/                   Batch draft generation (CSV / manual / saved contacts)
storage/                config.json read/write + data directory resolution
routes/                 Flask blueprints (one per page + debug)
templates/              Jinja2 templates + macros
static/                 CSS design system + Alpine.js stores + brand icons

app.py                  Flask factory — registers blueprints, auto-starts daemon
launcher.py             Entry point: data dir, stale-process eviction, port, browser
main.py                 CLI interface (run / bulk / contacts commands)
```

---

## Critical invariants — breaking these will crash or corrupt the app

1. **`EMAIL_AGENT_DATA_DIR` must be set before any `storage.app_config` import.**
   `launcher.py` does this. Never import app modules at module level in `launcher.py`
   before `os.environ["EMAIL_AGENT_DATA_DIR"]` is set.

2. **`daemon._append_log()` must never be called while `self._lock` is held.**
   `threading.Lock` is not reentrant. Calling it inside a `with self._lock:` block
   will deadlock.

3. **`Settings` is a frozen dataclass — never mutate it.**
   Reload by restarting the daemon: `daemon.stop(); daemon.start()`.

4. **`ReviewQueue` is in-memory only.** Contents are lost on process restart.
   Emails themselves are safe (marked `agent-processed` in Gmail), but generated
   drafts will need to be regenerated.

5. **The stop event must be set before the wake event in `daemon.stop()`.**
   Already done; don't reorder them.

---

## Data directory paths

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/EmailAgent/` |
| Windows | `%APPDATA%\EmailAgent\` |
| Development | `./data/` |

Key helpers in `storage/app_config.py`:
`get_contacts_path()`, `get_token_path()`, `get_credentials_path()`, `get_history_path()`,
`get_log_path()`, `get_debug_state_path()`, `get_traces_path()`

---

## Running in development

```bash
cd "/path/to/Email Agent"
source venv/bin/activate
python launcher.py          # opens browser at localhost:5001
```

Syntax check all Python files:
```bash
python -m py_compile $(find . -name "*.py" | grep -v venv | grep -v __pycache__)
```

Import sanity check after structural changes:
```bash
python -c "from core.config import Settings; from ai.generator import ReplyGenerator; \
           from gmail.client import GmailClient; print('imports OK')"
```

---

## Building the distributable

```bash
bash build_mac.sh           # → dist/Email Agent.app
build_windows.bat           # → dist/Email_Agent.exe
```

PyInstaller spec: `email_agent.spec`. The `hiddenimports` list must include any
module that PyInstaller can't auto-discover (typically modules loaded by string
or via lazy imports). After adding a new package, add it to `hiddenimports`.

---

## How to add a new Flask route

1. Create `routes/mypage.py` with a `Blueprint("mypage", __name__)`
2. Register in `app.py` `create_app()`:
   ```python
   from routes.mypage import mypage_bp
   app.register_blueprint(mypage_bp)
   ```
3. Add a sidebar link in `templates/base.html` nav section
4. Create `templates/mypage.html` extending `base.html`
5. Use macros from `templates/components/macros.html` for consistent UI

---

## How to add a new LLM provider

1. Create `ai/providers/myprovider.py` extending `LLMProvider` (see `base.py`)
   - Raise `ProviderUnavailableError` on soft failures (rate limit, timeout, 5xx)
   - Raise `GenerationError` on hard failures (invalid key, content policy)
2. Add new `Settings` fields to `core/config.py` for any credentials/config
3. Add to `load_settings_from_dict()` in `core/config.py`
4. Add to `_build_providers()` in `ai/generator.py`
5. Expose in `templates/settings.html` and `routes/settings.py`
6. Add to `hiddenimports` in `email_agent.spec`

---

## How to add a new Settings field

1. Add to `Settings` dataclass in `core/config.py` (frozen, always add with a default)
2. Add to `load_settings_from_dict()` using `optional()` or `require()`
3. Add to `routes/settings.py` POST handler's `updated` dict
4. Add input to `templates/settings.html` using existing macros
5. If the daemon needs it immediately: it reads settings from `load_config()` in
   `_build_components()`, so the daemon restart triggered by saving settings picks it up

---

## How to add a new email processing step

All per-email logic lives in `agent/pipeline.py` → `EmailPipeline._process_single()`.
The steps run in this order:

```
parse_thread()
  → contact_store.lookup()
  → _extract_greeting_names()
  → _should_skip_as_observer()   [structural skip — no Gemini]
  → generator.summarise()         [Gemini call 1]
  → generator.classify()          [Gemini call 2]
  → fetch_and_summarise()         [conditional: attachments only]
  → interaction_store.get_recent() [context retrieval]
  → build_user_message()
  → generator.generate()          [Gemini call 3]
  → assemble()
  → review_queue.push()
  → gmail.mark_as_processed()
```

To add a step: insert it at the appropriate point in `_process_single()`.
Always mark the email as processed before returning to avoid re-processing.

---

## Observability

The app writes structured JSON logs to `{DATA_DIR}/logs/agent.log` (rotating, 5 MB × 3).

**Debug Dashboard:** open `/debug` in the browser while the agent is running.
Shows: system health, IMAP status, token expiry, session stats, recent email processing
traces (expandable per-email decision log), and a live log tail.

**Debug Mode** (toggle in Settings → AI Configuration): enables full LLM prompt/response
logging. Off by default to avoid writing email content to disk.

**Trace files:** `{DATA_DIR}/debug/traces.json` — last 50 email traces, persisted.
**State file:** `{DATA_DIR}/debug/state.json` — daemon health snapshot, persisted.

---

## Common pitfalls

- **IMAP requires Gmail IMAP to be enabled.** Settings → Forwarding and POP/IMAP →
  Enable IMAP. The watcher degrades gracefully to 60-second polling if unavailable.

- **Bulk sends go to the Review Queue, not directly to Gmail Drafts.**
  Users send from `/review`, not from Gmail.

- **`routes/review.py` creates a new `GmailClient` on every send request.**
  This is by design — the OAuth token is always fetched fresh from `token.json`
  (which `TokenManager` keeps current). Do not cache the client across requests.

- **The `_process_single()` method in `pipeline.py` must always call
  `gmail.mark_as_processed()` before returning.** If it returns without marking,
  the same email will be re-processed on the next poll cycle.

- **Never call `merge_and_save_config()` from the daemon's main thread while
  holding `self._lock`.** This writes to disk and should not block the lock.

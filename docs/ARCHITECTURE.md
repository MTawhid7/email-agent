# Email Agent — Technical Architecture

> A deep-dive into the system design, implementation mechanics, known limitations, and future roadmap.

> **Latest additions (production systems):** Multi-provider LLM failover, per-contact interaction memory,
> IMAP IDLE real-time pipeline, historyId-based catch-up, and proactive token lifecycle management.
> See §6–10 for details.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository Layout](#2-repository-layout)
3. [Startup Sequence](#3-startup-sequence)
4. [Core Pipeline — End to End](#4-core-pipeline--end-to-end)
5. [Subsystem Reference](#5-subsystem-reference)
   - 5.1 Gmail OAuth & Token Management
   - 5.2 Email Parsing
   - 5.3 Gemini Integration
   - 5.4 Review Queue
   - 5.5 Email Assembly & Signature
   - 5.6 Contact Store
   - 5.7 Bulk Send
   - 5.8 Configuration & Storage
6. [Smart Filtering — Observer & Reply-Necessity Detection](#6-smart-filtering--observer--reply-necessity-detection)
7. [Desktop Packaging & Distribution](#7-desktop-packaging--distribution)
8. [Web UI Architecture](#8-web-ui-architecture)
9. [Design Decisions & Trade-offs](#9-design-decisions--trade-offs)
10. [Current Limitations](#10-current-limitations)
11. [Future Roadmap](#11-future-roadmap)

---

## 1. System Overview

Email Agent is a **locally-run AI email assistant**. It connects to a user's Gmail inbox, watches for new emails, and for each email that warrants a reply it drafts one using Google Gemini. Every draft lands in an in-app **Review Queue** — nothing is sent to Gmail until the user explicitly approves it.

### Core value propositions

| Problem | Solution |
|---|---|
| Manually reading and replying to every email is time-consuming | Agent drafts replies autonomously; human reviews in seconds |
| AI replies must never reach recipients without review | All drafts held in Review Queue; zero implicit sends |
| Teammates CC'd on external threads cause false replies | Observer-skip pre-filter based on To/CC/BCC headers |
| AI hallucinates contact details (phone, availability) | Knowledge Base injects factual grounding into every prompt |
| Non-technical coworkers cannot run Python scripts | Packaged as a native `.app` / `.exe` via PyInstaller |

### Technology summary

| Layer | Technology | Why |
|---|---|---|
| AI | Google Gemini (`google-genai`) | Multimodal, file-capable, free tier |
| Email | Gmail API v1 | Reliable, OAuth-scoped, thread-aware |
| Web framework | Flask 3.0 | Lightweight; single-user local server |
| Frontend reactivity | Alpine.js v3 | Zero-build, reactive stores, no bundler |
| CSS | Custom design token system | Consistent theming, dark sidebar |
| Packaging | PyInstaller + GitHub Actions | One `.app`/`.exe` for non-technical users |
| Auth | OAuth 2.0 via `google-auth-oauthlib` | Google-standard token refresh |
| Storage | JSON files on local disk | Zero infra; survives process restarts |

---

## 2. Repository Layout

```
Email Agent/
│
├── agent/
│   ├── daemon.py          # Lifecycle: start/stop, IMAP IDLE, token, historyId (~330 lines)
│   ├── pipeline.py        # Per-email AI processing: parse → skip → classify → generate → queue
│   └── queue.py           # Thread-safe in-memory ReviewQueue singleton (dict keyed by UUID)
│
├── ai/
│   ├── assembler.py       # Pure function: greeting + body + signature → final HTML
│   ├── generator.py       # ReplyGenerator — generate / classify / summarise / extract_topics
│   ├── prompts.py         # All prompt builders (system, classify, summarise, user message)
│   └── providers/
│       ├── base.py        # LLMProvider ABC
│       ├── router.py      # FallbackRouter — tries providers in order on soft failure
│       ├── gemini_provider.py
│       ├── openai_compatible_provider.py  # Groq, Grok, OpenAI, Mistral (httpx, no SDK)
│       └── ollama_provider.py
│
├── bulk/
│   └── bulk_sender.py     # Batch draft generation from CSV / manual list / contacts
│
├── contacts/
│   └── contact_store.py   # JSON-backed ContactProfile store (upsert, lookup, list)
│
├── core/
│   ├── config.py          # Settings frozen dataclass + load_settings_from_dict()
│   └── exceptions.py      # Typed exception hierarchy (AuthError, GenerationError, …)
│
├── email_parser/
│   ├── parser.py          # Gmail thread JSON → ParsedEmail dataclass
│   └── attachment_reader.py # Gemini Files API summarisation for PDFs/images
│
├── gmail/
│   ├── auth.py            # OAuth2 flow, token refresh, allow_oauth_flow guard
│   ├── client.py          # GmailClient — all Gmail API calls (threads, drafts, send, labels)
│   ├── imap_watcher.py    # IMAP IDLE watcher → fires wake_event on new mail
│   └── token_manager.py   # Background proactive token refresh (5 min ahead of expiry)
│
├── history/
│   └── interaction_store.py # Per-contact interaction memory (last 10 sent replies + topics)
│
├── observability/
│   ├── log_writer.py      # AgentLogger — rotating structured JSON log (5 MB × 3)
│   ├── state.py           # StateManager — persisted system health snapshot
│   └── trace.py           # ProcessingTrace + TraceStore (last 50 email traces)
│
├── routes/
│   ├── bulk.py            # /bulk — job submission + background progress tracking
│   ├── contacts.py        # /contacts — CRUD + CSV import
│   ├── dashboard.py       # / + /api/status + /api/agent/* + /api/shutdown
│   ├── debug.py           # /debug — live observability dashboard
│   ├── review.py          # /review — queue display, send/draft/discard actions
│   ├── settings.py        # /settings — config form + /api/auth/switch
│   ├── setup.py           # /setup/step1-4 — onboarding wizard + OAuth thread
│   └── templates_route.py # /templates — reply template library
│
├── signature/
│   └── signature.py       # HTML + plain-text signature builder; CDN icon URLs
│
├── storage/
│   └── app_config.py      # Path resolution, atomic config read/write, merge helpers
│
├── static/
│   ├── css/style.css      # Design token system (8pt grid, Inter, semantic colours)
│   ├── js/app.js          # Alpine.js stores: agentStore, reviewStore
│   └── icons/             # Brand icon PNGs (64px, served via jsDelivr CDN in emails)
│
├── templates/
│   ├── base.html          # Shell: fixed sidebar, content area, flash messages
│   ├── components/macros.html  # Jinja2 macros: input_field, btn, badge, avatar…
│   ├── dashboard.html
│   ├── contacts.html
│   ├── debug.html
│   ├── settings.html
│   ├── review.html
│   ├── bulk.html
│   ├── templates_page.html
│   └── setup/step1-4.html # Onboarding wizard pages
│
├── docs/
│   ├── ARCHITECTURE.md    # This file
│   └── SETUP.md
│
├── app.py                 # Flask factory; registers blueprints, auto-starts daemon
├── launcher.py            # Entry point: data dir, stale-instance eviction, port, browser
├── main.py                # CLI interface (run / bulk / contacts commands)
└── email_agent.spec       # PyInstaller build spec
```

---

## 3. Startup Sequence

Understanding the startup sequence is essential because it determines when the daemon becomes active and when the macOS network-access dialog appears.

```
launcher.main()
    │
    ├─ 1. Resolve writable data directory
    │     macOS: ~/Library/Application Support/EmailAgent/
    │     Windows: %APPDATA%\EmailAgent\
    │     Dev:    ./data/
    │     Set EMAIL_AGENT_DATA_DIR env var so storage/ can find it.
    │
    ├─ 2. Evict stale instance (Windows fix)
    │     _try_shutdown_old_instance(port=5001)
    │     → TCP connect probe to 127.0.0.1:5001
    │     → If something answers: POST /api/shutdown (0.3 s delayed os._exit)
    │     → Wait up to 5 s for port to free; fall back to next candidate port
    │
    ├─ 3. Bind port
    │     find_free_port([5001, 5002, 5003, 5004, 5005])
    │
    ├─ 4. Schedule browser open
    │     threading.Timer(1.5 s, webbrowser.open(f"http://localhost:{port}"))
    │
    ├─ 5. Import Flask app (triggers app.py module-level code)
    │     daemon = AgentDaemon()   ← created but not started yet
    │
    ├─ 6. create_app()
    │     Register all blueprints.
    │     Auto-start guard: if config.json exists AND token.json exists:
    │         daemon.start()       ← first network call happens here
    │                                (triggers macOS network-access dialog)
    │
    └─ 7. app.run(host="127.0.0.1", threaded=True)
          Flask blocks here; browser opens ~1.5 s later.
```

**Why auto-start matters:** Before this was added, users had to manually click "Start Agent" every time they launched the app. Non-technical users found this confusing. Auto-start fires immediately on launch when setup is complete, so the macOS network permission dialog appears right away rather than minutes later when the user eventually clicks the button.

---

## 4. Core Pipeline — End to End

This is the heart of the system. The `AgentDaemon` runs in a background thread and loops continuously until stopped.

### 4.1 Loop structure

```python
# agent/daemon.py — _run_loop() (simplified)

components = _build_components()   # one-time setup

while not stop_event.is_set():
    sleep_seconds = settings.poll_interval_seconds  # default 300
    try:
        count = _process_unread(*components, settings)
    except AuthError:
        set_error("..."); return        # fatal — stops the daemon
    except EmailAgentError:
        sleep_seconds = 30              # transient — retry quickly
    except Exception:
        sleep_seconds = 30

    # Interruptible sleep: checks stop_event every 0.5 s
    for _ in range(sleep_seconds * 2):
        if stop_event.is_set(): break
        time.sleep(0.5)
```

**Key design choice:** The sleep is broken into 0.5 s increments rather than one long `time.sleep(300)` so that `daemon.stop()` takes effect within half a second rather than waiting up to 5 minutes.

**Error recovery:** Transient errors (network blip, Gemini 500) drop `sleep_seconds` to 30 instead of the full poll interval. The daemon self-heals without requiring user intervention.

### 4.2 `_build_components()`

Called once before the loop begins. Builds all stateful objects that are reused across every poll cycle:

```
load_config()               → Settings frozen dataclass
get_credentials()           → valid OAuth2 Credentials (refresh if expired)
GmailClient(creds)          → Gmail API service wrapper
ReplyGenerator(settings)    → Gemini client, pre-built system prompt
ContactStore(contacts_path) → JSON-backed contact profiles
SignatureBuilder(settings)  → pre-rendered HTML signature
gmail.get_own_email()       → detect + save own_email if not in config
```

The `allow_oauth_flow=False` flag is critical here. Without it, the daemon thread would open a browser for OAuth — blocking the background thread indefinitely. When the token is missing or expired, the daemon raises `AuthError` instead, which surfaces as a "Re-connect Gmail" button on the dashboard.

### 4.3 `_process_unread()` — detailed walkthrough

This function processes one batch of up to 20 unread threads per poll cycle.

```
gmail.list_unread_thread_ids(max_results=20)
  └─ Gmail query: is:unread -label:agent-processed
                  -from:noreply -from:no-reply ...
                  -category:promotions -category:updates
```

Gmail's server-side query pre-filters obvious automated mail before any API round-trip per message. For each thread ID:

#### Step 1 — Fetch & Parse

```
gmail.get_thread(thread_id)
  └─ Returns full thread JSON with all messages and MIME parts

parse_thread(thread)
  └─ Extracts:
       sender_name, sender_email    from From: header of latest message
       subject                      from Subject: header
       latest_body                  decoded from text/plain > text/html MIME
       thread_messages              tuple of (sender, email, body) per message
       attachments                  tuple of AttachmentInfo structs
       to_addresses                 parsed from To: header (lowercase emails)
       cc_addresses                 parsed from CC: header (lowercase emails)
       message_id_header            RFC 5322 Message-ID for In-Reply-To threading
```

**MIME traversal:** Gmail encodes message bodies as base64url. The parser traverses the `multipart/*` tree recursively, preferring `text/plain` over `text/html` (to avoid sending BeautifulSoup-parsed HTML noise to Gemini). Only the latest message body is used for classification/generation; the full thread history is included in the reply-generation prompt for context.

#### Step 2 — Observer pre-filter (no Gemini call)

```python
_should_skip_as_observer(parsed, contact, settings)
```

This check runs before any Gemini API call, saving tokens for emails the agent structurally should not reply to.

Three skip conditions:
1. **CC-only:** `own_email` is in `cc_addresses` but not `to_addresses`
2. **BCC:** `to_addresses` is non-empty but `own_email` is absent from both To and CC — the email arrived but the user is invisible in headers (blind-copied)
3. **Teammate outbound:** sender's domain matches `team_domain` OR sender's contact has `is_teammate=True`, AND condition 1 or 2 applies

If skip fires → `gmail.mark_as_processed(message_id)` + activity log entry + `continue` to next thread.

**Why BCC detection works:** If `to_addresses` contains at least one address (the real recipient), but `own_email` is absent from both `to_addresses` and `cc_addresses`, the only way the email arrived is via BCC or a forwarding rule. Checking that `to_addresses` is non-empty guards against header-parse failures returning empty lists and causing false skips.

#### Step 3 — Thread summary (Gemini call #1)

```
generator.summarise(build_summary_prompt(parsed))
```

Single-sentence summary (≤12 words) of the thread. Used only for the activity log — shown next to each entry so the user can understand what was processed at a glance without opening the Review Queue.

#### Step 4 — Classify + reply-necessity check (Gemini call #2)

```
generator.classify(build_classification_prompt(parsed, contact, own_email))
```

The classification prompt includes:
- `own_email` so Gemini knows who "I" is
- Full `To:` and `CC:` address lists (already parsed — no extra API call)
- First 600 characters of the latest message body
- `known_contact` boolean (whether this sender is in the contact store)

Gemini returns:
```json
{
  "priority": "high | normal | low | skip",
  "needs_reply": true,
  "reason": "one sentence explanation"
}
```

**Two-dimensional decision:**
- `priority == "skip"` → newsletter, automated, bulk mail → skip
- `needs_reply == false` → informational only (FYI, announcement, receipt, out-of-office) → skip
- Any other combination → proceed to reply generation

The `needs_reply` field defaults to `true` in the fallback path (any JSON parse error) — this is intentional. A conservative fallback prevents emails from being silently dropped due to a model response formatting issue.

If `priority == "high"`, the `apply_priority_label` call adds the custom Gmail label `agent-high-priority` which shows up in the user's Gmail sidebar.

#### Step 5 — Attachment summarisation (conditional Gemini call)

```python
if parsed.attachments:
    attachment_summary = fetch_and_summarise(
        gmail_client, message_id, attachments, gemini_client, model
    )
```

PDFs and images are downloaded via `gmail.get_attachment()`, uploaded to the Gemini Files API (which handles large binary content), and summarised. The summary string is injected into the reply-generation prompt as `Attachment context: ...`.

This is skipped entirely when there are no attachments, avoiding unnecessary API calls.

#### Step 6 — Reply generation (Gemini call #3 or #4)

```
generator.generate(build_user_message(parsed, contact, mode="reply"))
```

The **system prompt** is pre-built once in `_build_components()` and reused for every message in the poll cycle. It contains:
- Persona instructions (how to write on the user's behalf)
- Auto-translate rule (if enabled)
- Knowledge Base facts (contact details, availability, company info)

The **user message** is built per email and contains:
- Sender identity and contact notes
- Tone override (if the contact has a preferred tone)
- Full thread history (oldest first) for context
- Attachment summary (if any)
- Task instruction

The system prompt + user message pattern means tone/persona context is consistent across all replies while the per-email context changes.

#### Step 7 — Assembly

```python
final_html = assemble(parsed.sender_first_name, body, signature_html)
```

`assemble()` is a pure function with no I/O:
- Wraps plain-text lines in `<p>` tags if Gemini returned plain text
- Prepends `<p>Dear {first_name},</p>`
- Appends the pre-rendered HTML signature

The signature contains brand icon links served from jsDelivr CDN (`cdn.jsdelivr.net/gh/{owner}/{repo}@main/static/icons/...`) as `<img>` tags with HTTPS URLs. Gmail strips `data:` URIs and inline SVG, so CDN-hosted PNGs are the only reliable option.

#### Step 8 — Queue & mark processed

```python
review_queue.push({
    "id": item_id,           # UUID
    "sender_name": ...,
    "sender_email": ...,
    "subject": "Re: ...",
    "thread_id": ...,
    "message_id_header": ...,  # for In-Reply-To threading
    "latest_message_id": ...,  # for mark_as_processed
    "body_html": final_html,
    "priority": priority,
    "summary": summary,
    "created_at": datetime.now().isoformat(),
})
gmail.mark_as_processed(parsed.latest_message_id)
```

`mark_as_processed` applies the `agent-processed` Gmail label. The inbox query in `list_unread_thread_ids` excludes this label, so the same thread is never processed twice — even if the daemon restarts before the user acts on it.

The activity log entry is added with `level="pending"` (amber) at this point. When the user sends or discards the draft, `resolve_review_item(item_id, "sent"|"discarded")` updates the log entry's level in-place.

---

## 5. Subsystem Reference

### 5.1 Gmail OAuth & Token Management

**Files:** `gmail/auth.py`, `gmail/token_manager.py`

The OAuth flow has two modes controlled by the `allow_oauth_flow` parameter:

```
allow_oauth_flow=True  (setup wizard, /api/auth/switch)
  → Opens browser via InstalledAppFlow.run_local_server(port=0)
  → Waits for user consent
  → Saves token to token.json

allow_oauth_flow=False (daemon thread)
  → If token missing or expired with no refresh_token: raises AuthError immediately
  → If token expired but has refresh_token: calls creds.refresh(Request()) silently
  → Never opens a browser — daemon threads must never block on user input
```

**Token refresh** happens transparently when the access token expires (every ~1 hour). The refresh token is long-lived but, under Google's Testing OAuth mode, expires after **7 days**. When refresh fails, the daemon raises `AuthError`, the `/api/status` endpoint exposes the error string, and the dashboard shows a "Re-connect Gmail" button.

**Scope:** `gmail.modify` (not `gmail.readonly`) is required because the agent needs to apply labels (`mark_as_processed`, `apply_priority_label`) and create/send drafts.

**Token path:** `{DATA_DIR}/credentials/token.json`
**Credentials path:** `{DATA_DIR}/credentials/credentials.json` (or `sys._MEIPASS/credentials/credentials.json` in frozen builds)

See §System 5 (Proactive Token Lifecycle Management) for background refresh details.

### 5.2 Email Parsing

**File:** `email_parser/parser.py`

Gmail returns threads as nested JSON. The top-level structure is:
```json
{
  "id": "thread_id",
  "messages": [
    {
      "id": "message_id",
      "payload": {
        "headers": [{"name": "From", "value": "..."}, ...],
        "mimeType": "multipart/mixed",
        "parts": [...]
      }
    }
  ]
}
```

The parser builds a `_header_map` (lowercased header name → value) for each message and traverses the MIME tree recursively. The traversal priority for body extraction is: `text/plain` > `text/html` > nested `multipart`. HTML bodies are passed through BeautifulSoup's `.get_text()` to strip tags before sending to Gemini — Gemini handles plain text better and the HTML structure adds no value for classification or reply generation.

`to_addresses` and `cc_addresses` are extracted from the **latest message** (not the first). This is important: in a multi-turn thread, the latest message's recipients reflect who is currently in the conversation.

Address parsing uses regex `[\w.+-]+@[\w.-]+\.\w+` on the full header value (which may contain display names like `"Alice <alice@example.com>, Bob <bob@example.com>"`). This is intentionally simple — RFC 5321 address parsing is complex and the regex covers all real-world cases adequately.

### 5.3 Gemini Integration & LLM Failover

**Files:** `ai/generator.py`, `ai/providers/`

`ReplyGenerator` delegates all LLM calls to a `FallbackRouter` that holds an ordered list of providers. On any `ProviderUnavailableError` (rate limit, timeout, 5xx), the router transparently tries the next provider. Hard failures (`GenerationError`: invalid key, content policy) propagate immediately.

```
FallbackRouter.generate()
    ├── GeminiProvider          (primary — google-genai SDK)
    ├── OpenAICompatibleProvider (Groq / xAI Grok / OpenAI / Mistral — httpx only, no SDK)
    └── OllamaProvider          (local model, no API key, requires Ollama installed)
```

**System prompt caching:** Built once in `ReplyGenerator.__init__()` and stored as `self._system_prompt`. Contains persona instructions, knowledge base facts, and auto-translate rule — all constant for a given settings load. Passed to every provider at construction time.

**Three distinct Gemini calls per email:**

| Call | System instruction | Purpose |
|---|---|---|
| `summarise()` | "You are a concise email summariser." | One-sentence thread summary for activity log |
| `classify()` | "You are an email classifier. Return JSON only." | Priority + needs_reply determination |
| `generate()` | Full persona system prompt | Reply body generation |

The `classify()` call uses a separate system instruction (not the persona prompt) because classification is a structured reasoning task, not a writing task. Mixing the two would produce worse JSON and worse replies.

### 5.4 Review Queue

**File:** `agent/queue.py`

A `threading.Lock`-protected in-memory `dict[str, dict]` keyed by item UUID. The module exports a single `review_queue = ReviewQueue()` singleton. Both the daemon (writer) and the review route (reader/mutator) share this singleton directly — no message passing, no serialisation.

**Thread safety:** `push`, `get`, `remove`, `all`, and `count` are all wrapped in `with self._lock`. The daemon's `_append_log` does NOT hold the daemon's internal lock when it calls queue operations — Python's `threading.Lock` is not reentrant, so holding it while calling into another locked object would deadlock.

**Persistence gap:** The queue is in-memory only. If the Flask process restarts while items are in the queue, they are lost. The emails themselves are safe (they remain unread in Gmail and will be re-processed on the next poll — the `agent-processed` label was already applied, so re-processing would be skipped). This means lost queue items do not cause duplicate sends but do lose the generated draft text.

**Activity log vs. queue:** These are two separate data structures. The activity log (`self._logs`, a `deque` in the daemon) is for display only. The review queue is for actionable items. When a user acts on a review item, `resolve_review_item(item_id, action)` walks the log `deque` and updates the matching entry's `level` field from `"pending"` to `"success"` or `"discarded"`.

### 5.5 Email Assembly & Signature

**Files:** `ai/assembler.py`, `signature/signature.py`

`assemble()` is a **pure function** — it has no side effects and no I/O. It takes three strings and returns one. This makes it trivially testable and reusable in both the daemon pipeline and the bulk sender.

The signature builder (`SignatureBuilder`) constructs the HTML once per daemon lifecycle (in `_build_components()`). Building the signature is I/O-free after construction.

**Social link icon delivery:** Gmail's security model strips:
- Inline `<style>` blocks
- `data:` URIs (base64-encoded images)
- `<svg>` elements

The only reliable way to show brand icons is `<img src="https://...">` pointing to an externally hosted HTTPS URL. The solution uses jsDelivr CDN (`cdn.jsdelivr.net/gh/MTawhid7/email-agent@main/static/icons/{platform}.png`) which serves directly from the public GitHub repository. The PNG files are 64×64 px brand icons generated with macOS `sips` from branded SVGs, displayed at 28×28 px in the email for 2× sharpness.

For unknown platforms (custom links not in the 11 recognised brands), the Google favicon service (`www.google.com/s2/favicons?domain={domain}&sz=64`) is used as a fallback.

### 5.6 Contact Store

**File:** `contacts/contact_store.py`

`ContactProfile` is a **frozen dataclass** (immutable after creation). Storage is a single `contacts.json` file — a dict keyed by lowercase email address:

```json
{
  "alice@example.com": {
    "email": "alice@example.com",
    "name": "Alice Johnson",
    "company": "Acme Corp",
    "relationship_type": "client",
    "notes": "Prefers concise replies; decision-maker for Q3 contract",
    "tone": "Formal",
    "is_teammate": false
  }
}
```

`_make()` uses `{k: v for k, v in record.items() if k in known}` to construct the dataclass — unknown keys are silently ignored. This means adding new fields to `ContactProfile` is backward-compatible with existing `contacts.json` files (old records simply don't have the new key; the field defaults apply).

`upsert()` is the only write method — it handles both create and update. Since the email is the key, editing a contact via the web form submits to the same `POST /contacts` endpoint as creating one.

**Contact data injected into prompts:** When a contact exists, the reply-generation prompt includes:
- Relationship type
- Company
- Notes (free-form, most important)
- Tone override (triggers specific instruction in the user message)
- `is_teammate` (used by observer-skip, not injected into prompts)

### 5.7 Bulk Send

**File:** `bulk/bulk_sender.py`, `routes/bulk.py`

Bulk send generates one personalised Gmail draft per recipient without sending anything — the user reviews drafts in Gmail's native Drafts folder. Three input modes feed the same pipeline:

```
Input mode "manual"   → _parse_manual_recipients(form) → temp CSV
Input mode "csv"      → uploaded file → temp CSV
Input mode "contacts" → selected emails → contact store lookup → temp CSV
                                                                     ↓
                                                            _load_csv()
                                                                     ↓
                                               for each row: _process_row()
                                                                     ↓
                                                       gmail.create_draft()
```

Each job runs in a **background thread** (`threading.Thread(daemon=True)`) so the Flask request returns immediately. Progress is tracked in `_jobs: dict[str, dict]` with a `threading.Lock`. The frontend polls `GET /api/bulk/status/{job_id}` every 2 seconds to render the progress bar.

Temp CSV files are always deleted in the `finally` block of `_run_bulk_job()` regardless of success or failure.

`_process_row()` merges CSV notes with stored contact notes (stored notes take priority, CSV notes are appended). It builds a stub `ParsedEmail` to reuse the shared `build_user_message()` prompt builder — this ensures bulk and reply modes produce stylistically consistent output.

### 5.8 Configuration & Storage

**Files:** `storage/app_config.py`, `core/config.py`

All file paths are resolved through `_data_dir()` which reads `EMAIL_AGENT_DATA_DIR` at call time. This late-binding is critical: `launcher.py` sets the env var before importing Flask, so by the time any route imports `storage.app_config`, the correct data directory is already set.

`save_config()` uses **atomic rename** (write to `.tmp`, then `tmp.replace(config.json)`). This prevents config corruption if the process is killed mid-write.

`Settings` is a **frozen dataclass** loaded once at daemon startup from the JSON config. It is the single source of truth for runtime behaviour. The daemon does not watch for config changes — changes take effect on the next start (or immediately if "Save Settings" triggers a daemon restart via the settings route).

### 5.9 Observability

**Files:** `observability/log_writer.py`, `observability/trace.py`, `observability/state.py`

Three independent observability layers, all writing to `{DATA_DIR}/debug/` and `{DATA_DIR}/logs/`:

**`AgentLogger` (`log_writer.py`):** Rotating structured JSON log (`agent.log`, 5 MB × 3 files). Each line is a JSON object with `timestamp`, `level`, `event`, and event-specific fields. Surfaced as a live tail on the `/debug` page.

**`TraceStore` (`trace.py`):** Keeps the last 50 per-email processing traces in memory and persists them to `traces.json`. Each trace records every decision made for one email: skip reason, classification priority, greeting mismatch note, generation time. Expandable per-email accordion on `/debug`.

**`StateManager` (`state.py`):** Persists a health snapshot to `state.json` on every daemon cycle — daemon running state, IMAP status, token expiry, draft count, last poll time. Loaded at startup so `/debug` shows meaningful data even before the daemon runs its first cycle.

The **Debug Dashboard** at `/debug` aggregates all three layers into a single page: system health cards, per-email trace accordion, and a live structured log tail.

---

## 6. Smart Filtering — Observer & Reply-Necessity Detection

This is the most nuanced part of the system. It prevents the agent from generating replies in situations where no reply is warranted, saving Gemini API quota and avoiding embarrassing outbound emails.

### Two-tier architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 1: Structural pre-filter (no Gemini API call)                    │
│                                                                        │
│  _should_skip_as_observer()                                            │
│  • own_email derived from: settings.own_email OR self._detected_email  │
│    (auto-fetched via gmail.get_own_email() on first run)               │
│  • Check To:/CC: headers already parsed into to_addresses/cc_addresses │
│  • Three skip triggers:                                                │
│      CC-only:    own_email in cc_addresses AND not in to_addresses     │
│      BCC:        to_addresses non-empty AND own_email absent from both │
│      Teammate:   sender is internal AND user is CC/BCC                 │
│  • Greeting cross-check (CC/BCC only): _names_match() compares the    │
│    greeted name against _user_name_variants() — see §Greeting below   │
└────────────────────────────────────────────────────────────────────────┘
                              ↓ passes
┌────────────────────────────────────────────────────────────────────────┐
│  Tier 2: Semantic classification (Gemini call)                         │
│                                                                        │
│  generator.classify(build_classification_prompt(...))                  │
│  • priority == "skip": newsletter, marketing, automated, bulk          │
│  • needs_reply == false: FYI, announcement, receipt, out-of-office,   │
│    group update where no individual reply is expected                  │
│  • greeting_note injected when _names_match() finds no match and user  │
│    is not a direct addressee — soft hint only, Gemini decides          │
│  • Fallback: needs_reply=True on any parse failure (conservative)      │
└────────────────────────────────────────────────────────────────────────┘
                              ↓ passes
               Reply generation proceeds
```

### Greeting name matching

**Files:** `agent/pipeline.py` — `_extract_greeting_names()`, `_names_match()`, `_user_name_variants()`

The pipeline extracts the greeted name from the first 250 characters of the email body (regex pattern: `hi / hello / dear / hey …`). This is compared against the user's known name variants via `_names_match()`, which runs three passes in order of cost:

| Pass | Example | Rule |
|---|---|---|
| Exact | "tawhid" == "tawhid" | Direct set membership |
| Prefix | "tawhid" starts "tawhidul" | Shorter token ≥ 4 chars must be a prefix of the longer |
| Fuzzy | "tarek" ≈ "tareq" | Both ≥ 4 chars, length diff ≤ 2, `SequenceMatcher.ratio()` ≥ 0.80 |

`_user_name_variants()` builds the user's variant set from three sources:
1. Tokens from `settings.signature_name` split on whitespace/dots ("Md. Tawhidul Islam" → `{"md", "tawhidul", "islam"}`)
2. Tokens from the email address prefix (`mtawhidulislam7` → `{"mtawhidulislam7"}`)
3. Entries from `settings.name_aliases` (comma-separated, e.g. `"Muhammad, Mohamed, Tawhid, Tareq"`)

The greeting check only triggers a **hard skip** when the user is already identified as a CC/BCC observer. For direct `To:` recipients, a greeting mismatch only adds a soft `greeting_note` hint to the Gemini classifier — it never blocks processing unilaterally.

### Teammate identification

A sender is classified as an internal teammate if **either** of these is true:
1. Their email domain suffix matches `settings.team_domain` (e.g. `@technyx.com`)
2. Their `ContactProfile.is_teammate == True`

The two-signal approach handles teammates who use personal email addresses (Gmail, Outlook) that don't match the company domain.

### own_email auto-detection

On first daemon run after setup, if `settings.own_email` is empty, the daemon calls `gmail.get_own_email()` (`users.getProfile` API) and saves the result to `config.json` via `merge_and_save_config`. This is surfaced in the Gmail Account card on the Settings page as "Connected as user@example.com" — users never need to enter their own email manually.

---

## 7. Desktop Packaging & Distribution

### Build pipeline

GitHub Actions builds the `.app` and `.exe` on every push to `main`:

```yaml
# macOS: PyInstaller → .app bundle → zip
pyinstaller email_agent.spec --noconfirm
zip -r Email-Agent-Mac.zip "dist/Email Agent.app"

# Windows: PyInstaller → .exe → zip
pyinstaller email_agent.spec --noconfirm
Compress-Archive dist\Email_Agent.exe Email-Agent-Windows.zip
```

PyInstaller bundles:
- All Python source and dependencies
- `templates/` and `static/` directories (copied verbatim)
- `credentials/credentials.json` (identifies the Google Cloud application — not user-specific)

### Bundle identifier stamping (macOS)

macOS Gatekeeper caches bundle identifiers. If two versions of an app have the same bundle ID, Gatekeeper can show a `-47` error on the second launch. The spec stamps each build with the GitHub Actions run number:

```python
# email_agent.spec
_build_number = os.environ.get("BUILD_NUMBER", "dev")
# → com.emailagent.app.42, com.emailagent.app.43, ...
```

Each build is treated as a distinct app by Gatekeeper, requiring one "Open Anyway" approval per version (not per-launch).

### Stale process eviction (Windows)

Windows keeps a process in memory even after its `.exe` is deleted from disk. If a user downloads a new version without terminating the old one, `find_free_port()` would bind the new instance to port 5002 while the old one stays on 5001 — two instances coexist, both writing to the same data directory.

Fix: `launcher._try_shutdown_old_instance(port=5001)` runs before port selection:
1. TCP probe to `127.0.0.1:5001`
2. If connected: `POST http://localhost:5001/api/shutdown`
3. `/api/shutdown` calls `daemon.stop()` then `os._exit(0)` after 300 ms
4. Launcher waits up to 5 s for the port to free
5. `find_free_port()` now finds 5001 available

If the old instance is too old to have `/api/shutdown`, the wait times out and the new instance falls back to port 5002 (one-time degraded experience).

### Data directory isolation

Runtime data (config, token, contacts, templates) lives in the OS-standard user data directory, completely separate from the application bundle:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/EmailAgent/` |
| Windows | `%APPDATA%\EmailAgent\` |
| Development | `./data/` |

This means:
- Updating the app never wipes user data
- Multiple app versions share the same config/contacts
- The app can be deleted and reinstalled without losing settings

---

## 8. Web UI Architecture

### Flask structure

Flask is run with `threaded=True` (the default since Flask 1.0). Every browser request gets its own thread from Werkzeug's thread pool. The daemon runs in a separate, long-lived daemon thread. Communication between the daemon and routes happens through shared mutable state:

```python
# app.py — module-level singletons
daemon = AgentDaemon()           # routes import this directly
review_queue = ReviewQueue()     # also module-level; shared singleton
```

This is safe because:
- `AgentDaemon` protects mutable state with `threading.Lock`
- `ReviewQueue` protects its dict with `threading.Lock`
- `daemon._logs` is a `collections.deque` — `deque.append()` is thread-safe in CPython without a lock

### Alpine.js reactive stores

The dashboard avoids page reloads by polling `/api/status` every 5 seconds via Alpine.js:

```javascript
Alpine.store('agent', {
    running: false, logs: [], draftCount: 0, reviewCount: 0,
    toggling: false, pollInterval: 300,

    init() {
        this.refresh();
        setInterval(() => this.refresh(), 5000);
    },

    async refresh() { /* fetch /api/status, update all fields */ },

    async toggle() {
        // Stop path: POST /api/agent/stop returns {"running": false} immediately.
        // The stop event is set; the daemon thread will exit at its next 0.5 s checkpoint.
        // Start path: two 600 ms refresh cycles suffice because daemon starts near-instantly.
    }
});
```

**Stop button correctness:** `/api/agent/stop` returns `running: false` immediately after setting the stop event — it does NOT wait for `thread.join()`. This is intentional: if the daemon is mid-Gemini-API-call (which can take 5–30 seconds), blocking on the join would cause the stop button to appear frozen. The stop event being set is the authoritative signal — no new work will start.

### Jinja2 templating

All UI components use a single macro file (`templates/components/macros.html`) as the source of truth. Common components — `input_field`, `textarea_field`, `toggle_field`, `btn`, `badge`, `avatar`, `empty_state` — are rendered as Jinja2 macros rather than duplicated HTML. This ensures visual consistency and makes design-system changes a single-file edit.

Flash messages use Flask's session-based flash system, rendered in `base.html` and styled as `alert-success` / `alert-error` components.

---

## 9. Design Decisions & Trade-offs

### Why Flask instead of FastAPI or Django?

Flask is synchronous and single-process. For a local desktop application with a single concurrent user, async adds complexity without benefit. Flask's simplicity means the entire web layer is understandable without framework expertise. Django would bring an ORM and admin interface that are overkill for JSON file storage.

### Why JSON files instead of SQLite?

For a single-user local app, JSON files are:
- Human-readable and debuggable without tooling
- Trivially portable (copy a directory to migrate)
- Zero-dependency (no DB driver)
- Atomic via write-to-temp-then-rename

The main cost is O(n) full-file reads on every contact lookup. At the expected scale (<1000 contacts) this is imperceptible. SQLite would be the right choice if the user base grows to multiple accounts or thousands of contacts.

### Why Alpine.js instead of React/Vue?

The entire frontend is served as static files from Flask. A full SPA framework would require a build pipeline (Webpack/Vite), package.json, and separate dev server — incompatible with PyInstaller's static-file bundling. Alpine.js is loaded from CDN (or could be vendored) and requires no compilation. The reactive store pattern provides all the interactivity needed (polling, conditional rendering, optimistic UI updates) with ~100 lines of JavaScript.

### Why threading instead of multiprocessing or async?

The daemon accesses shared in-memory state (review queue, activity log) with Flask routes. `multiprocessing` would require IPC serialisation. `asyncio` would require rewriting the entire Gemini SDK usage as async. Python's `threading` with explicit `Lock` objects is the simplest correct solution. The GIL is not a concern here — the daemon spends most of its time waiting on I/O (Gemini API, Gmail API), not on CPU-bound Python computation.

### Why `requests` scope (`gmail.modify`) rather than `gmail.send`?

`gmail.modify` is a superset that allows reading, labelling, drafting, and sending. A narrower `gmail.readonly` + `gmail.send` combination would require two separate OAuth scopes, complicating the consent screen. `gmail.modify` is the standard scope for email assistant applications.

---

## 10. Current Limitations

### Authentication & Security

| Limitation | Impact | Detail |
|---|---|---|
| OAuth Testing mode | 7-day token expiry for users | Google caps Testing mode apps at 100 users; tokens expire weekly and require manual re-authentication via the "Re-connect Gmail" button |
| No encryption of stored credentials | token.json is plaintext on disk | OAuth tokens are not secrets in the traditional sense (they are scoped and revocable) but they do grant Gmail access; on shared machines this is a risk |
| Single OAuth application | All users share `credentials.json` | The OAuth client ID identifies the application; individual users have separate tokens |

### Reliability & Persistence

| Limitation | Impact | Detail |
|---|---|---|
| In-memory review queue | Lost on process restart | Items in the queue that haven't been acted on are gone if Flask restarts; emails won't be regenerated because `agent-processed` label already applied |
| No idempotency on generation | Potential duplicates | If the daemon crashes after `review_queue.push()` but before `mark_as_processed()`, the same email will be processed again on restart and a second queue item created |
| Poll-based inbox checking | Up to N-minute reply latency | Default 300 s poll interval means emails can sit unprocessed for 5 minutes; Gmail Push Notifications (Pub/Sub webhooks) would reduce this to near-real-time |
| No retry tracking | Failed generation silently drops | If Gemini generation fails for a specific email (not a transient error), the error is logged but the email is not re-queued; it remains with `agent-processed` label applied |

### AI Quality & Safety

| Limitation | Impact | Detail |
|---|---|---|
| `needs_reply` is Gemini-dependent | Occasional false negatives | If Gemini misclassifies an email as not needing a reply, it is silently skipped; no feedback mechanism exists to correct this |
| No reply preview before queue | User sees full generated draft | There is no "skeleton" or intent preview; users must read the full draft in the Review Queue |
| Context window truncation | Long threads lose early context | Only the first 600 chars of the latest body are shown to the classifier; the full thread is shown to the generator but very long threads may be truncated by the model's context window |
| No tone calibration loop | Replies may drift from expectations | The system does not learn from edits the user makes in the Review Queue; every email starts from the same persona prompt |

### Scalability

| Limitation | Impact | Detail |
|---|---|---|
| Single user per instance | Cannot serve a team from one server | The `daemon` and `review_queue` are process-global singletons; running multiple Gmail accounts requires multiple separate app instances |
| No rate-limit awareness beyond Gemini | Gmail API quotas ignored | The Gmail API has per-user quotas (250 quota units/second); the agent does not implement any Gmail-side rate limiting |
| Synchronous Flask routes | Review actions block the request thread | `send_message()` and `create_draft()` make synchronous Gmail API calls in the request handler; slow responses block other requests |

### Platform-Specific

| Limitation | Platform | Detail |
|---|---|---|
| macOS Gatekeeper prompt per version | macOS | Unsigned apps require "Open Anyway" once per bundle identifier version; this is a one-time step but confusing for non-technical users |
| Manual kill required for old instances without shutdown endpoint | Windows | Users on a pre-shutdown-endpoint build must kill the old process via Task Manager before launching a new version |
| BCC detection is indirect | All | BCC recipients are invisible in email headers by design; the system infers BCC when `to_addresses` is non-empty but `own_email` is absent — this could theoretically misfire if `own_email` is misconfigured |

---

## 11. Future Roadmap

### Short-term (next 3–6 months)

#### Gmail Push Notifications (replacing polling)
Instead of polling every N seconds, subscribe to Gmail's Pub/Sub push notifications. The Gmail API can push a notification to a Cloud Pub/Sub topic whenever the inbox changes. The agent would listen on a local webhook, eliminating the poll interval delay entirely and reducing Gmail API quota usage by ~99%.

**Complexity:** Requires a Cloud Pub/Sub topic, a service account, and a stable HTTPS endpoint (or a local ngrok-equivalent for desktop use). Significant infrastructure addition.

#### Persistent review queue (SQLite)
Replace the in-memory `ReviewQueue` dict with a SQLite table:
```sql
CREATE TABLE review_items (
    id TEXT PRIMARY KEY,
    sender_name TEXT, sender_email TEXT, subject TEXT,
    thread_id TEXT, message_id_header TEXT, latest_message_id TEXT,
    body_html TEXT, priority TEXT, summary TEXT,
    status TEXT DEFAULT 'pending',   -- pending / sent / discarded
    created_at TEXT, resolved_at TEXT
);
```
Benefits: items survive process restarts; historical record of all processed emails; can query for patterns (which senders always get discarded?).

#### Feedback loop for `needs_reply`
When the user discards a draft, present a one-click "Don't reply to emails like this" option. Store the reason as a rule in `config.json` and prepend it to the classification prompt. Over time, the system learns the user's specific skip preferences beyond the global defaults.

#### OAuth production verification
Submit the app for Google's OAuth verification. Once verified:
- Token expiry extends from 7 days to 6 months (or indefinitely with offline access)
- No 100-user cap
- "This app is unverified" warning disappears

**Complexity:** Requires a privacy policy URL, a homepage, and Google's manual review process.

### Medium-term (6–12 months)

#### Multi-account support
Run multiple daemon instances (one per Gmail account) within a single Flask process. The daemon pool would be a `dict[account_id, AgentDaemon]` instead of a single singleton. The UI would have an account switcher in the sidebar. Each account would have isolated `token.json`, `contacts.json`, and `config.json` files in a subdirectory.

**Complexity:** Significant refactor of module-level singletons into per-account scoped objects.

#### Reply learning from edits
Before the user clicks "Send", detect if they edited the generated reply. Log the diff. Use these diffs to fine-tune the persona prompt — either by automatically prepending observed patterns ("you often remove greetings" → add "Do not include a greeting line") or by exposing a "Writing Style Insights" panel.

#### Template suggestion
After processing 50+ emails, cluster the generated replies by intent and surface them as suggested templates in the Template Library. The user approves which ones to save as reusable starters.

#### Attachment action items
The current attachment summarisation produces a text block for context. Extend it to extract **action items** from attachments (e.g. "The invoice attached requests payment by 2026-06-01") and surface these as structured fields in the Review Queue item.

### Long-term (12+ months)

#### Web-hosted mode
A Docker-deployed version where users authenticate through the web UI instead of downloading an app. This would require:
- Proper multi-tenancy (per-user isolated data, separate daemon threads)
- Secrets management (encrypt tokens at rest per user)
- HTTPS termination
- Session management
- Potentially moving from file storage to PostgreSQL

#### Scheduled drafts
Allow the agent to queue a reply for sending at a specific time (e.g. "send this at 9am Monday"). Requires a scheduler (APScheduler or Celery Beat) and a `scheduled_at` field in the review queue.

#### Mobile companion app
A read-only companion that shows the Review Queue and allows approve/discard actions from a phone. Would communicate with the locally-running Flask server via LAN, or through an optional cloud relay for remote access.

#### Analytics dashboard
A separate `/analytics` page showing:
- Emails processed per day / week
- Skip rate breakdown (observer, newsletter, no-reply-needed)
- Average reply generation time
- Most active senders
- Tone distribution across sent replies

#### Automated reply rules
Beyond the current classification, allow users to define rules: "If sender is in [VIP list] and subject contains 'invoice', skip the Review Queue and send immediately with template [Invoice Received]." This brings the system closer to a rule-based + AI hybrid automation platform.

---

## Appendix — Key Data Flows

### Setup wizard

```
Step 1: Enter Gemini API key + model → merge_and_save_config()
Step 2: Auto-detect credentials.json (bundled) → merge_and_save_config({path})
Step 3: Enter signature details + social links → merge_and_save_config()
Step 4: Enter persona + poll interval → merge_and_save_config()
         → start_oauth_thread()
         → background: get_credentials(allow_oauth_flow=True)
         → browser opens, user consents
         → token.json written
         → _oauth_state["done"] = True
         → frontend polling /setup/api/oauth_status detects done
         → redirect to /dashboard
         → auto-start daemon (app.py create_app guard triggers on next launch)
```

### Review Queue item lifecycle

```
daemon._process_unread()
  └─ review_queue.push(item)           level = "pending" (amber)
  └─ gmail.mark_as_processed()         prevents re-processing

User opens /review
  └─ review_queue.all()                sorted by created_at desc

User clicks "Send Now"
  └─ gmail.send_message(...)
  └─ review_queue.remove(item_id)
  └─ daemon.resolve_review_item(id, "sent")   level = "success" (green)

User clicks "Save Draft"
  └─ gmail.create_draft(...)
  └─ review_queue.remove(item_id)
  └─ daemon.resolve_review_item(id, "sent")   level = "success" (green)

User clicks "Discard"
  └─ review_queue.remove(item_id)
  └─ daemon.resolve_review_item(id, "discarded")  level = "discarded" (gray)
```

### Settings change with daemon restart

```
User edits settings → POST /settings
  └─ validate required fields
  └─ save_config(updated)              atomic rename write
  └─ if daemon.is_running:
       daemon.stop()                   sets _stop_event
       time.sleep(1)                   allow in-flight Gemini call to finish
       daemon.start()                  _build_components() re-reads config.json
                                       → picks up new persona, poll interval, etc.
  └─ flash("Settings saved")
  └─ redirect /settings
```

---

## Production Systems (added for high-volume team use)

### System 1 — Multi-Provider LLM Failover

**Problem:** Gemini 429/503 under load silently drops emails.

**Architecture:** Provider abstraction layer in `ai/providers/` with a `FallbackRouter` that tries providers in order and moves to the next on any soft failure (`ProviderUnavailableError`).

```
FallbackRouter.generate()
    ├── GeminiProvider          (primary — existing Gemini logic, extracted)
    ├── OpenAICompatibleProvider (any OpenAI-compatible API)
    │     Groq:   api.groq.com/openai/v1  ← recommended free option
    │     Grok:   api.x.ai/v1
    │     OpenAI: api.openai.com/v1
    │     Mistral: api.mistral.ai/v1
    └── OllamaProvider          (local model, no API key, free)
```

Soft failures (→ next provider): 429, 503, 5xx, network timeout
Hard failures (→ propagate immediately): 401 invalid key, content policy

Uses `httpx` directly — no `openai` SDK dependency. Configured in **Settings → AI Fallback Providers**.

---

### System 2 — Per-Contact Interaction History

**Problem:** Every email generated in isolation — recurring contacts get no continuity.

**Storage:** `{DATA_DIR}/history/interactions.json` — dict keyed by sender email, value is a list of up to 10 `InteractionRecord` objects (newest-first):

```json
{
  "alice@example.com": [
    {
      "thread_id": "18abc123",
      "date": "2026-05-22",
      "subject": "Re: Q3 proposal",
      "summary": "Alice asking about pricing and timeline",
      "our_reply_summary": "Sent revised estimate and confirmed Q3 delivery",
      "topics": ["pricing", "q3-proposal", "delivery-timeline"]
    }
  ]
}
```

**Recording trigger:** When the user clicks **Send Now** or **Save as Draft** in the Review Queue, `AgentDaemon.resolve_review_item(item_id, "sent")` looks up `_pending_history[item_id]` (set at reply-generation time) and writes to `InteractionStore`.

**Data computed at generation time** (not retrieval time): `summarise_reply()` and `extract_topics()` are called once when the reply is generated and stored in `_pending_history`. No extra LLM calls at retrieval time.

---

### System 3 — Context-Aware Reply Generation

**Token budget per email generation:**
```
Current thread (complete):          ~2,000 tokens
Contact notes (static):             ~100 tokens
Recurring topic tags:               ~30 tokens
Last 5 interaction summaries:       ~500 tokens
Global knowledge base:              ~200 tokens
System prompt (persona):            ~300 tokens
                                    ──────────────
Total:                              ~3,130 tokens  ← trivial for any model
```

**Context injection point:** `build_user_message()` in `ai/prompts.py` accepts `recent_interactions` and `recurring_topics` as optional parameters. All existing callers (bulk sender, CLI) are unchanged — both parameters default to `None`.

**No runtime summarisation:** Interaction summaries are pre-computed at send time. `get_recent()` retrieves compact strings — no LLM call in the hot path.

---

### System 4 — IMAP IDLE + historyId Hybrid Pipeline

**Problem:** 5-minute poll interval; missed emails when offline.

**Architecture:** Two components replace the single polling `time.sleep()` loop:

**`gmail/imap_watcher.py` — ImapIdleWatcher:**
- Persistent TLS connection to `imap.gmail.com:993`
- XOAUTH2 authentication using the OAuth2 access token
- `IDLE` command — server sends `* N EXISTS` when new mail arrives
- Fires `wake_event` immediately on notification
- Re-IDLE every 28 minutes (Gmail's 29-minute IDLE limit)
- On token refresh: reconnects with fresh XOAUTH2
- On any failure: exponential back-off reconnect (1s → 60s)
- Graceful degradation: if IMAP unavailable, fires `wake_event` every 60s (fast polling fallback)

**`_process_unread_incremental()` in daemon:**
- Waits on `wake_event` with 60s timeout (IMAP notification or heartbeat)
- Calls `gmail.history_list(last_history_id)` → returns only threads added since last run
- Persists new `last_history_id` to `config.json` after each successful batch
- On 404 (`HistoryExpiredError`): falls back to `list_unread_thread_ids()`, resets cursor

**historyId guarantee:** Gmail retains history for 30 days. If the app is offline for less than 30 days, every email is recovered on restart. The cursor is stored in `config.json` under key `last_history_id`.

---

### System 5 — Proactive Token Lifecycle Management

**Problem:** OAuth access tokens expire every ~60 minutes. Synchronous refresh only triggered on failure; blocks operations; can crash the IMAP session.

**`gmail/token_manager.py` — TokenManager:**
- Holds credentials in a `threading.RLock`-protected variable
- Background thread checks expiry every 30 seconds
- Refreshes proactively 5 minutes before expiry
- On refresh: saves to `token.json`, notifies registered callbacks
- `ImapIdleWatcher` registers a callback: on token refresh → reconnect IMAP with fresh XOAUTH2
- On refresh failure: logs warning, retries in 60s — **never crashes the daemon**
- On `invalid_grant` (refresh token revoked): raises `TokenRefreshError` → daemon surfaces "Re-connect Gmail" button

**Token flow:**
```
TokenManager._refresh_loop() (every 30s check)
    │ expiry ≤ 5 min away
    ▼
creds.refresh(Request()) → save token.json
    │ notify_callbacks
    ▼
ImapIdleWatcher.on_token_refreshed()
    │ sets reconnect_flag
    ▼
idle_loop() checks flag → logout → reconnect with fresh XOAUTH2 → re-IDLE
```

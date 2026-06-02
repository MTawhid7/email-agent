# Email Agent

A local AI-powered email assistant that reads your Gmail inbox, generates personalized replies using Google Gemini, and surfaces them in a review queue for you to edit, send, or discard — all from a browser UI that runs on your own machine.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?style=flat-square)
![Flask](https://img.shields.io/badge/Flask-3.0-lightgrey?style=flat-square)
![Gemini](https://img.shields.io/badge/Gemini-AI-orange?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Build](https://img.shields.io/github/actions/workflow/status/MTawhid7/email-agent/build.yml?style=flat-square&label=Build)

---

## Overview

Email Agent polls your Gmail inbox on a configurable interval, classifies each message by priority, generates a contextual reply using your personal persona prompt, and places it in an in-app review queue. You open the browser UI, review the draft, make edits if needed, and hit **Send** — or save it to Gmail Drafts, or discard it entirely. Nothing reaches Gmail without your explicit approval.

The app packages as a native desktop application (`.app` on macOS, `.exe` on Windows) via GitHub Actions — no Python installation required for end users.

---

## Features

| Feature | Description |
|---|---|
| **Review Queue** | All AI-generated replies held for human review before touching Gmail |
| **Priority Scoring** | Emails classified as High / Normal / Low / Skip using Gemini |
| **Newsletter Detection** | Automated, promotional, and no-reply emails are silently skipped |
| **Thread Summarisation** | One-sentence summary of each thread shown in the activity log |
| **Reply Tone Per Contact** | Override the global persona with Formal / Professional / Casual / Brief per sender |
| **Template Library** | 15 pre-built reply templates across 5 categories; fully editable |
| **Auto-Translate** | Detect incoming email language and reply in the same language |
| **Attachment Summarisation** | PDFs and images summarised via Gemini Files API and injected into reply context |
| **Bulk Send** | Generate personalised drafts for multiple recipients — enter manually, upload a CSV, or pick from saved contacts |
| **Contact Management** | Per-contact notes and tone preferences; mark contacts as Teammates; add individually, import from CSV, or select in bulk send |
| **Teammate-Aware Skipping** | Automatically skips emails where you are only CC'd — distinguishes observer threads from emails that need a reply |
| **Fuzzy Name Matching** | Name aliases field accepts alternate spellings and nicknames (e.g. "Muhammad, Tawhid, Tareq"). Greeting matching uses prefix and fuzzy similarity so "Tarek" matches "Tareq" and "Tawhidul" matches "Tawhid" — prevents false skips on transliterations and typos |
| **Multi-Provider LLM Failover** | Gemini is primary; Groq / xAI Grok / OpenAI / Ollama used as fallback on rate limits or outages |
| **Conversation Memory** | Per-contact interaction history — recent replies and recurring topics injected into every generation prompt |
| **Real-Time Inbox** | IMAP IDLE push notifications replace polling; replies are generated within seconds of email arrival |
| **Reliable Catch-up** | Gmail historyId cursor persists across restarts — no emails missed even after hours offline |
| **Proactive Token Refresh** | OAuth token refreshed 5 minutes before expiry in the background; IMAP session reconnects automatically |
| **Social Link Icons** | Brand icons (LinkedIn, GitHub, WhatsApp, etc.) in email signature via jsDelivr CDN |
| **Knowledge Base** | Free-form facts injected into every AI prompt — prevents hallucinated phone numbers / contact details |
| **Review Status Tracking** | Activity log reflects pending → sent / discarded state after user action |
| **Debug Dashboard** | Live observability panel at `/debug` — system health, IMAP status, per-email processing traces, and a structured log tail |
| **Bulk Draft Review** | Bulk-generated drafts appear in the in-app Review Queue; edit, send, or discard without leaving the app |
| **Gmail Account Switcher** | Switch Gmail accounts from Settings without re-running the setup wizard |
| **Smart Filtering** | CC/BCC header detection + greeting-name mismatch + Gemini reply-necessity check — three layers before generating any reply |
| **Desktop App** | Packaged as `.app` / `.exe` via PyInstaller — no terminal required for end users; new version auto-evicts the old process on launch |

---

## Architecture

```
Email Agent/
├── agent/                  # Background daemon + review queue
│   ├── daemon.py           # Lifecycle: start/stop, IMAP IDLE, token, historyId
│   ├── pipeline.py         # Per-email AI pipeline: parse → skip → classify → generate → queue
│   └── queue.py            # Thread-safe in-memory ReviewQueue singleton
├── ai/                     # AI generation layer
│   ├── assembler.py        # Pure function: greeting + body + signature → HTML
│   ├── generator.py        # ReplyGenerator with LLM failover
│   ├── prompts.py          # All prompt builders
│   └── providers/          # GeminiProvider, OpenAICompatibleProvider, OllamaProvider
├── bulk/
│   └── bulk_sender.py      # Batch draft generation from CSV / manual / saved contacts
├── contacts/
│   └── contact_store.py    # JSON-backed contact profiles
├── core/
│   ├── config.py           # Settings frozen dataclass + JSON/env loaders
│   └── exceptions.py       # Typed exception hierarchy
├── email_parser/
│   ├── parser.py           # Gmail thread → ParsedEmail dataclass
│   └── attachment_reader.py # Gemini Files API attachment summarisation
├── gmail/                  # Gmail API + OAuth + IMAP IDLE
│   ├── auth.py             # OAuth2 flow (allow_oauth_flow parameter)
│   ├── client.py           # GmailClient — all Gmail API calls
│   ├── imap_watcher.py     # IMAP IDLE watcher → fires wake_event on new mail
│   └── token_manager.py    # Background proactive token refresh
├── history/
│   └── interaction_store.py # Per-contact interaction memory (last 10 sent replies)
├── observability/          # Debugging and monitoring
│   ├── log_writer.py       # AgentLogger — rotating structured JSON log
│   ├── state.py            # StateManager — persisted system health snapshot
│   └── trace.py            # ProcessingTrace + TraceStore (last 50 email traces)
├── routes/                 # Flask blueprints (one per page + debug)
├── signature/
│   └── signature.py        # HTML + plain-text email signature builder
├── storage/
│   └── app_config.py       # config.json read/write + data directory resolution
├── templates/              # Jinja2 templates + macros
├── static/                 # CSS design system + Alpine.js stores + brand icons
├── app.py                  # Flask factory — registers blueprints, auto-starts daemon
├── launcher.py             # Entry point: data dir, stale-process eviction, port, browser
├── main.py                 # CLI interface (run / bulk / contacts commands)
└── email_agent.spec        # PyInstaller build spec
```

**Data flow:**

```
Gmail Inbox
    │ history_list() / list_unread_thread_ids()   ← IMAP IDLE triggers immediately
    ▼
AgentDaemon._process_unread_incremental()
    └─ EmailPipeline.process_batch(thread_ids)
           ├─ parse_thread()              → ParsedEmail
           ├─ _should_skip_as_observer()  → structural skip (To/CC/BCC + greeting check)
           ├─ summarise()                 → thread summary (Gemini call 1)
           ├─ classify()                  → priority / skip (Gemini call 2)
           ├─ fetch_and_summarise()       → attachment context (Gemini Files API, conditional)
           └─ generate()                  → reply body (Gemini call 3)
                │ assemble()              → greeting + body + HTML signature
                ▼
          ReviewQueue (in-memory)
               │ user action via /review
               ├─ send_message()  → sends immediately
               ├─ create_draft()  → saves to Gmail Drafts
               └─ discard()       → removed, no Gmail action
```

---

## Requirements

- Python 3.11 or higher
- A Google account with Gmail enabled
- A [Gemini API key](https://aistudio.google.com/app/apikey) (free tier available)
- A Google Cloud project with the Gmail API enabled and an OAuth 2.0 Desktop credentials file

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/MTawhid7/email-agent.git
cd email-agent
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 3. Set up Google Cloud credentials

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable the **Gmail API** (APIs & Services → Library)
3. Configure the **OAuth consent screen** (Google Auth Platform → Audience → add your Gmail as a test user)
4. Create an **OAuth 2.0 Client ID** → Application type: **Desktop app** → Download JSON
5. Place the downloaded file at `credentials/credentials.json`

### 4. Run the app

```bash
python launcher.py
```

Your browser opens to `http://localhost:5001`. The 4-step setup wizard guides you through entering your Gemini API key, configuring your signature, and connecting Gmail (one-time OAuth consent).

---

## Desktop App Distribution

Pre-built binaries are produced automatically by GitHub Actions on every push to `main`.

### Download

1. Go to the **Actions** tab in the repository
2. Click the latest **Build Desktop App** workflow run
3. Download **Email-Agent-Mac** or **Email-Agent-Windows** from the Artifacts section

### macOS first launch

macOS blocks unsigned apps on first open. After unzipping:

1. Double-click `Email Agent.app`
2. Open **System Settings → Privacy & Security → Open Anyway**

This is a one-time step. Subsequent launches open normally.

> **Updating:** Each build has a unique bundle identifier, so macOS treats new versions as distinct apps and shows the security prompt once per version rather than showing a stale-cache error.

### Updating on Windows

When you launch a new version, it automatically signals the old process to exit and claims port 5001. If you are on an older build that does not yet have this behaviour, kill the old process manually first:

1. Press **Ctrl + Shift + Esc** to open Task Manager
2. Find `Email Agent.exe` in the list
3. Right-click → **End Task**
4. Launch the new version normally

### Build locally

```bash
# macOS
bash build_mac.sh

# Windows
build_windows.bat
```

Requires PyInstaller (`pip install pyinstaller`). Output is placed in `dist/`.

---

## Configuration

All settings are managed through the web UI (Settings page) and stored in:

- **macOS:** `~/Library/Application Support/EmailAgent/config.json`
- **Windows:** `%APPDATA%\EmailAgent\config.json`
- **Development:** `data/config.json`

| Setting | Description |
|---|---|
| Gemini API Key | Your key from Google AI Studio |
| Model | Gemini model name (default: `gemini-3.1-flash-lite`) |
| Poll interval | How often the agent checks your inbox (seconds) |
| Persona instructions | How the AI should write on your behalf |
| Knowledge Base | Factual grounding — real phone, email, availability, company info |
| Auto-translate | Detect incoming language and reply in the same language |
| Your Email Address | Your Gmail address — used to detect whether you are To: or only CC: on an email |
| Team Domain | e.g. `yourcompany.com` — all senders from this domain are treated as teammates |
| Fallback API Key | API key for a secondary LLM provider (Groq, xAI Grok, OpenAI, Mistral — any OpenAI-compatible API) |
| Fallback Model | Model name for the fallback provider (default: `llama-3.3-70b-versatile` for Groq) |
| Fallback Base URL | API endpoint — change this URL to switch provider without code changes |
| Ollama | Optional local model fallback — free, no API key, requires Ollama installed |
| Name Aliases | Comma-separated alternate names / nicknames (e.g. `Muhammad, Tawhid, Tareq`). Used by the greeting-match check to avoid misidentifying emails addressed to a variant of your name |
| Signature | Name, title, company, phone, social links with brand icons |

---

## Sharing with Coworkers

The app is designed for team distribution. Each person uses their own Gmail account and Gemini API key — the shared `credentials.json` identifies the application, not any individual user.

**Steps to onboard a new user:**

1. Add their Gmail address as a test user in your Google Cloud Console  
   (Google Auth Platform → Audience → Test users → + Add Users)
2. Share the downloaded `.app` or `.exe` with them
3. They double-click, complete the 4-step setup wizard, and they're running

**Token expiry:** Google OAuth tokens for apps in Testing mode expire every 7 days. When this happens, the dashboard shows a **Re-connect Gmail** button — one click opens the browser for a new sign-in, then the agent restarts automatically.

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI (primary) | [Google Gemini](https://ai.google.dev/) (`google-genai`) |
| AI (fallback) | Any OpenAI-compatible API via `httpx` — Groq, xAI Grok, OpenAI, Mistral, Ollama |
| Email | [Gmail API v1](https://developers.google.com/gmail/api) (`google-api-python-client`) |
| Real-time inbox | IMAP IDLE (`imapclient`, XOAUTH2) + Gmail History API cursor |
| Web framework | [Flask](https://flask.palletsprojects.com/) 3.0 |
| Frontend | [Alpine.js](https://alpinejs.dev/) (reactive stores), [Inter](https://rsms.me/inter/) font, custom CSS design system |
| Packaging | [PyInstaller](https://pyinstaller.org/) + GitHub Actions |
| Auth | OAuth 2.0 via `google-auth-oauthlib` with proactive background refresh |

---

## Development Workflow

For rapid iteration during development, run the app directly from source — no build required:

```bash
cd "/path/to/Email Agent"
git pull
source venv/bin/activate
python launcher.py
```

The browser opens to `http://localhost:5001` and uses the same data directory as the packaged app (`~/Library/Application Support/EmailAgent/` on macOS), so your config, token, and contacts are preserved between runs.

**Build the `.app` / `.exe`** only when distributing a stable version to coworkers — not for every code change.

---

## Project Status

The core pipeline (classify → summarise → generate → review → send) is production-ready for personal and small-team use. The app is in Google OAuth **Testing** mode, which limits use to explicitly added test users (up to 100).

---

## License

MIT License. See [LICENSE](LICENSE) for details.

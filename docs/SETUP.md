# Email Agent — Setup Guide

This guide walks you through every step required to get the Email Agent running on your machine, from creating API credentials to sending your first personalized draft.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Install Python Dependencies](#2-install-python-dependencies)
3. [Get a Gemini API Key](#3-get-a-gemini-api-key)
4. [Set Up Gmail API Credentials](#4-set-up-gmail-api-credentials)
5. [Configure Your .env File](#5-configure-your-env-file)
6. [First Run — Gmail Authorization](#6-first-run--gmail-authorization)
7. [Using Reply Mode (Daemon)](#7-using-reply-mode-daemon)
8. [Using Bulk Send Mode](#8-using-bulk-send-mode)
9. [Managing Contacts](#9-managing-contacts)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

Before you begin, make sure the following are installed on your machine:

| Requirement | Version | Check |
|---|---|---|
| Python | 3.11 or higher | `python3 --version` |
| pip | latest | `pip --version` |
| A Google account | Gmail enabled | — |

If Python is not installed, download it from [python.org](https://python.org).

---

## 2. Install Python Dependencies

Open a terminal, navigate to the project folder, and run:

```bash
cd "/Users/tawhid/Documents/Email Agent"
pip install -r requirements.txt
```

This installs:
- `google-genai` — Gemini AI SDK (generates email replies)
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client` — Gmail API access
- `beautifulsoup4` — strips HTML from incoming email bodies
- `python-dotenv` — loads your `.env` config file
- `click` — powers the CLI commands

> **Tip:** If you get a permissions error, use `pip install --user -r requirements.txt` or create a virtual environment first:
> ```bash
> python3 -m venv venv
> source venv/bin/activate    # macOS / Linux
> venv\Scripts\activate       # Windows
> pip install -r requirements.txt
> ```

---

## 3. Get a Gemini API Key

1. Go to **[Google AI Studio](https://aistudio.google.com/app/apikey)** and sign in with your Google account.
2. Click **Create API key**.
3. Select an existing Google Cloud project or create a new one when prompted.
4. Copy the generated API key — it starts with `AIza...`.
5. Keep it safe. You will paste it into your `.env` file in the next step.

> The `gemini-3.1-flash-lite` model is available on the free tier. Check [ai.google.dev/gemini-api/docs/pricing](https://ai.google.dev/gemini-api/docs/pricing) for current limits.

---

## 4. Set Up Gmail API Credentials

This is the most involved step. You need to create an OAuth2 "Desktop App" credential in Google Cloud Console so the agent can read your Gmail and save drafts.

### Step 4.1 — Create or select a Google Cloud project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click the project dropdown at the top and select **New Project**.
3. Give it a name (e.g. `email-agent`) and click **Create**.
4. Make sure the new project is selected in the dropdown.

### Step 4.2 — Enable the Gmail API

1. In the left sidebar, go to **APIs & Services → Library**.
2. Search for `Gmail API`.
3. Click on it and press **Enable**.

### Step 4.3 — Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**.
2. Choose **External** and click **Create**.
3. Fill in the required fields:
   - **App name:** `Email Agent` (or any name)
   - **User support email:** your Gmail address
   - **Developer contact information:** your Gmail address
4. Click **Save and Continue** through the Scopes and Test Users screens (no changes needed).
5. Click **Back to Dashboard**.
6. Under **Publishing status**, leave it as **Testing** for personal use.
7. Click **+ Add Users** and add your own Gmail address as a test user.

   > This is required while the app is in "Testing" mode. Only accounts you add here can authorize the agent.

### Step 4.4 — Create OAuth2 Credentials

1. Go to **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. Set **Application type** to **Desktop app**.
4. Give it a name (e.g. `email-agent-desktop`) and click **Create**.
5. A dialog will show your Client ID and Client Secret — click **Download JSON**.
6. Rename the downloaded file to `credentials.json`.
7. Move it into the `credentials/` folder inside the project:
   ```
   Email Agent/
   └── credentials/
       └── credentials.json   ← place it here
   ```

---

## 5. Configure Your .env File

1. In the project folder, copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Open `.env` in any text editor and fill in your values:

```env
# ── Gemini ────────────────────────────────────────────────────────────────────
GEMINI_API_KEY=AIzaSy...          # paste your key from Step 3
GEMINI_MODEL=gemini-3.1-flash-lite

# ── Gmail ─────────────────────────────────────────────────────────────────────
GMAIL_CREDENTIALS_PATH=credentials/credentials.json
POLL_INTERVAL_SECONDS=300         # check inbox every 5 minutes

# ── AI Persona ────────────────────────────────────────────────────────────────
PERSONA_PROMPT=You are Tawhid, a professional software developer. Reply concisely and warmly. Always address the sender by their first name. Never make commitments about deadlines.

# ── Signature ─────────────────────────────────────────────────────────────────
SIGNATURE_NAME=Tawhid Islam
SIGNATURE_TITLE=Software Developer
SIGNATURE_COMPANY=Your Company
SIGNATURE_PHONE=+1 (555) 000-0000
SIGNATURE_LINKEDIN=https://linkedin.com/in/yourhandle
SIGNATURE_GITHUB=https://github.com/yourhandle
SIGNATURE_WEBSITE=https://yourwebsite.com
```

**Field reference:**

| Variable | Required | Description |
|---|---|---|
| `GEMINI_API_KEY` | Yes | Your Gemini API key from Google AI Studio |
| `GEMINI_MODEL` | Yes | Exact model name, e.g. `gemini-3.1-flash-lite` |
| `GMAIL_CREDENTIALS_PATH` | Yes | Path to your OAuth2 `credentials.json` |
| `POLL_INTERVAL_SECONDS` | No (default: 300) | How often the daemon checks for new emails |
| `PERSONA_PROMPT` | Yes | Instructions for how the AI should write replies |
| `SIGNATURE_NAME` | Yes | Your full name in the email signature |
| `SIGNATURE_TITLE` | No | Job title shown in the signature |
| `SIGNATURE_COMPANY` | No | Company name shown in the signature |
| `SIGNATURE_PHONE` | No | Phone number in the signature |
| `SIGNATURE_LINKEDIN` | No | LinkedIn profile URL |
| `SIGNATURE_GITHUB` | No | GitHub profile URL |
| `SIGNATURE_WEBSITE` | No | Personal website URL |

> **Security:** Never commit your `.env` file to git. It contains your API keys.
> Add `.env` to your `.gitignore` if you initialize a repository.

---

## 6. First Run — Gmail Authorization

Run the agent for the first time:

```bash
python main.py
```

**What happens:**

1. The agent loads your `.env` configuration and validates all required fields.
2. It detects that no `credentials/token.json` exists yet.
3. **Your default browser opens automatically** to a Google sign-in page.
4. Sign in with the Gmail account you added as a test user in Step 4.3.
5. Google will show a warning: **"Google hasn't verified this app"** — this is expected for apps in Testing mode. Click **Continue**.
6. Grant the requested permission: **"Read, compose, send, and permanently delete all your email from Gmail"** — click **Allow**.
7. The browser shows a success message: `The authentication flow has completed.`
8. Back in your terminal, the daemon starts:

```
[2026-05-19 10:05:00] Polling inbox every 300s — press Ctrl+C to stop.
[2026-05-19 10:05:01] No new emails.
```

A `credentials/token.json` file is now saved. On all future runs, the browser will **not** open again — the token is refreshed silently.

> **If the browser does not open automatically**, copy the URL printed in the terminal and paste it manually into your browser.

---

## 7. Using Reply Mode (Daemon)

The daemon continuously polls your Gmail inbox for unread emails and generates a personalized draft reply for each one.

### Start the daemon

```bash
python main.py
```

Or explicitly:

```bash
python main.py run
```

With a custom max threads per poll:

```bash
python main.py run --max 10
```

### What the daemon does for each unread email

1. Reads the full thread history (all messages, oldest to newest)
2. Looks up the sender in your contact store (if a profile exists, their notes are injected into the prompt)
3. Sends the thread + persona + contact notes to Gemini and receives a reply body
4. Prepends `Dear {first name},` to the reply
5. Appends your configured signature and social links
6. Saves the result as a **draft** in Gmail — inside the original thread
7. Labels the email `agent-processed` so it is never processed again

### Reviewing and sending drafts

1. Open **Gmail** in your browser.
2. Go to **Drafts** in the left sidebar.
3. Each draft is pre-addressed to the sender and placed inside their thread.
4. Review the content, edit if needed, and click **Send**.

### Stop the daemon

Press `Ctrl+C` in the terminal.

---

## 8. Using Bulk Send Mode

Bulk mode lets you send a personalized version of the same email to many people at once. Each person gets a draft with their own name and optionally their own contextual notes.

### Prepare your recipients CSV

Create a file (e.g. `recipients.csv`) with the following columns:

```csv
name,email,notes
Alice Johnson,alice@example.com,"Client since 2024, prefers brief emails"
Bob Smith,bob@example.com,"Technical background, can use industry terms"
Carol Lee,carol@example.com,
```

- `name` — required. The recipient's full name.
- `email` — required. The recipient's email address.
- `notes` — optional. Context about this person that Gemini will use to personalize the email.

A template is available at `recipients.csv.example`.

### Run bulk mode

```bash
python main.py bulk --csv recipients.csv --intent "Follow up on our Q2 project proposal"
```

**Options:**

| Option | Required | Description |
|---|---|---|
| `--csv` | Yes | Path to your recipients CSV file |
| `--intent` | Yes | What the email is about (used as subject and context for Gemini) |

### Output

```
[2026-05-19 11:00:01] Draft created for Alice Johnson <alice@example.com>
[2026-05-19 11:00:03] Draft created for Bob Smith <bob@example.com>
[2026-05-19 11:00:05] Draft created for Carol Lee <carol@example.com>
[2026-05-19 11:00:05] Bulk send complete. Check Gmail Drafts.
```

Each draft is saved independently in your Gmail Drafts folder. Review and send them at your own pace.

---

## 9. Managing Contacts

The contact store lets you save per-person notes that are injected into the AI prompt every time the agent processes an email from that address. This enables richer, more contextually aware replies.

### Add or update a contact

```bash
python main.py contacts add \
  --email alice@example.com \
  --name "Alice Johnson" \
  --company "Acme Corp" \
  --relationship "client" \
  --notes "Prefers concise responses. Decision maker for Q3 budget."
```

All fields except `--email` are optional.

### List all contacts

```bash
python main.py contacts list
```

Output:

```
  alice@example.com  |  Alice Johnson  |  Acme Corp  |  Prefers concise responses.
  bob@example.com    |  Bob Smith      |             |  Technical background.
```

### Where contacts are stored

Contacts are saved in `contacts/contacts.json`. You can edit this file directly in a text editor if preferred — it is plain JSON, keyed by lowercase email address.

---

## 10. Troubleshooting

### "Missing required environment variable: GEMINI_API_KEY"

Your `.env` file is missing or the variable is empty. Open `.env` and make sure all required fields are filled in. Ensure the file is in the same directory as `main.py`.

---

### "Gmail credentials file not found"

The file `credentials/credentials.json` does not exist. Re-download it from Google Cloud Console → APIs & Services → Credentials → your OAuth client → Download JSON, and place it in the `credentials/` folder.

---

### "Access blocked: This app's request is invalid" (during OAuth)

You did not add your Google account as a test user. Go to Google Cloud Console → APIs & Services → OAuth consent screen → Test users → Add your Gmail address.

---

### "Gmail credentials expired or revoked. Delete credentials/token.json and re-run."

Your OAuth token has been revoked (this happens if you change scopes or revoke access in your Google account settings). Delete `credentials/token.json` and run `python main.py` again to re-authorize.

---

### "Invalid Gemini API key. Check GEMINI_API_KEY in your .env file."

The `GEMINI_API_KEY` value in your `.env` is incorrect or has been revoked. Get a fresh key from [Google AI Studio](https://aistudio.google.com/app/apikey).

---

### "Gemini rate limit exceeded after retries."

You have hit the free-tier request limit for the Gemini API. The agent retries automatically with exponential backoff, but if the limit persists, wait a minute and try again. Check your quota at [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Gemini API → Quotas.

---

### The daemon runs but creates no drafts

- Check that the emails you expect to see are **unread** in Gmail (not already read).
- Check that they do not have the `agent-processed` label (if they do, remove it in Gmail or ignore them — they have already been processed).
- Increase verbosity by temporarily reducing `POLL_INTERVAL_SECONDS=30` to confirm the daemon is polling.

---

### Drafts appear as new emails instead of replies in the thread

This can happen if Gmail did not return a `Message-ID` header for the original email. The draft is still created correctly — it just won't be visually threaded. Open the draft, manually set the `To` field and send normally.

---

### CSV bulk mode skips some rows with "missing email — skipped"

The `email` column in the affected row is blank. Open your CSV, ensure every row has a valid email address, and re-run.

---

### Mac App displays Error -47 ("The application can't be opened")

If you downloaded a new version of the `.zip` release, macOS Gatekeeper may block it because of a caching bug tied to the app name.
**Fix:** Rename the `Email Agent.app` (e.g., to `Email Agent 2.app`) in Finder. When you launch it again, macOS will prompt you for permission in **System Settings > Privacy & Security**. After approving, the app will open normally.

# WhatsApp Bot Service — Design & Implementation Guide

> **Status:** Planned — not yet implemented. This document covers the complete
> technical design for a standalone WhatsApp bot service that runs alongside the
> existing email agent.

---

## Overview

A separate Python service (port 5002) that handles WhatsApp conversations for customer
engagement, re-engagement, and follow-up. It runs on the same machine as the email
agent, shares the same customer database and AI engine, and costs nothing to operate.

**No cloud infrastructure. No Meta approval. No per-message charges.**

---

## What the Bot Can Do

### Conversational

| Capability | Detail |
|---|---|
| Receive messages | Customers send a WhatsApp message, bot gets it within seconds |
| Auto-respond with AI | Reply generated from full customer context (purchase history, past conversations, contact notes) |
| Maintain conversation state | Remembers the current and past sessions per customer number |
| Multi-turn conversations | Full back-and-forth, not just single messages |
| Handle media | Receive and send images, PDFs, voice notes, documents |
| Menus / quick replies | "Reply 1 for pricing, 2 for support" style interactions |
| Language detection | Detects incoming language and replies in kind (auto-translate already in the email agent) |

### Business

| Capability | Detail |
|---|---|
| Answer FAQs | "What are your services?" → AI answers from the knowledge base in Settings |
| Qualify leads | "What's your budget?" → collect info, store in customer profile |
| Purchase follow-up | "You bought X 3 months ago — interested in Y?" |
| Re-engagement | Proactive messages to lapsed customers who have opted in |
| Complaint detection | Detect frustration keywords, notify team by email, give customer a handoff message |
| Human escalation | "Let me connect you with our team" → sends email notification to staff |
| Status updates | "Your project is in review — we'll reach out by Friday" |
| Promotional broadcasts | Batch outbound messages to opted-in customers |

---

## Technical Approach: whatsapp-web.js Bridge

The bot uses the **unofficial WhatsApp Web protocol** via the open-source
[whatsapp-web.js](https://github.com/pedroslopez/whatsapp-web.js) library. This is
the same approach used by hundreds of thousands of small business WhatsApp bots.

**Authentication:** A one-time QR code scan (identical to opening WhatsApp Web on a
laptop) links a phone number to the bot. The session is saved locally and persists
across restarts.

**Why unofficial vs Meta's official API:**
- Official Meta API requires template approval for outbound messages, a Meta Business
  account, and charges per conversation ($0.02–$0.08 / conversation)
- whatsapp-web.js is free, has no template restrictions, and requires no Meta account
- Risk: WhatsApp can block accounts that send spam; legitimate customer service use
  is effectively never affected

---

## Architecture

```
Customer's WhatsApp
        ↕  (WhatsApp Web protocol over WebSocket)
whatsapp_bridge/index.js    Node.js, port 3001 — thin relay (~80 lines)
        ↕  HTTP (localhost only)
whatsapp_bot/               Python Flask, port 5002 — AI + business logic
        ↕  shared JSON files
Email Agent                 Python Flask, port 5001 — unchanged
```

The Node.js bridge handles only the WhatsApp protocol. All AI generation, customer
context, and business logic remains in Python, reusing the existing `ReplyGenerator`,
`ContactStore`, and `InteractionStore`.

---

## Directory Structure

```
whatsapp_bridge/
├── package.json             # deps: whatsapp-web.js, express, axios, qrcode-terminal
└── index.js                 # ~80 lines: QR auth, forward inbound, expose send API

whatsapp_bot/
├── app.py                   # Flask factory (port 5002)
├── bot_daemon.py            # Core: receive → contextualise → generate → reply
├── bot_bridge.py            # HTTP client to the Node.js bridge
├── conversation_store.py    # Per-number WA conversation history
└── routes/
    ├── webhook.py           # POST /wa/incoming  (from Node bridge)
    └── broadcast.py         # POST /wa/send      (outbound campaigns)

customers/                   # shared with email agent
└── customer_store.py        # CustomerProfile + PurchaseRecord
```

---

## Node.js Bridge (`whatsapp_bridge/index.js`)

```javascript
const { Client, LocalAuth } = require('whatsapp-web.js');
const express = require('express');
const axios   = require('axios');

const PYTHON_BOT_URL = 'http://localhost:5002';
const client = new Client({ authStrategy: new LocalAuth() });

// Show QR code in terminal for one-time scan
client.on('qr', qr => require('qrcode-terminal').generate(qr, {small: true}));
client.on('ready', () => console.log('WhatsApp bot connected.'));

// Forward all inbound messages to Python bot service
client.on('message', async msg => {
    if (msg.fromMe) return;   // ignore echo of our own sends
    await axios.post(`${PYTHON_BOT_URL}/wa/incoming`, {
        from:      msg.from,              // number@c.us
        body:      msg.body,
        type:      msg.type,             // text / image / document / audio
        timestamp: msg.timestamp,
        name:      msg._data.notifyName, // display name if available
    }).catch(console.error);
});

// HTTP API for Python to send messages
const app = express();
app.use(express.json());
app.post('/send', async (req, res) => {
    const { to, message } = req.body;
    await client.sendMessage(to + '@c.us', message);
    res.json({ ok: true });
});

client.initialize();
app.listen(3001, () => console.log('Bridge listening on :3001'));
```

---

## Python Bot Service

### `whatsapp_bot/bot_daemon.py`

```python
class WhatsAppBotDaemon:

    def handle_incoming(self, phone: str, body: str, name: str) -> None:
        """
        Called when a customer sends a WhatsApp message.
        1. Load WA conversation history for this phone number
        2. Look up CustomerProfile (shared DB — purchase history, notes, tone)
        3. Look up email InteractionStore for cross-channel context
        4. Build WhatsApp-optimised prompt (1-3 short sentences, casual tone)
        5. Generate reply via existing ReplyGenerator (with LLM failover)
        6. Send via bot_bridge → Node.js → WhatsApp
        7. Append message pair to ConversationStore
        8. Check for escalation keywords → notify staff by email if needed
        """

    def send_outbound(self, phone: str, message: str) -> None:
        """Send a proactive message (campaign, follow-up) to an opted-in customer."""
```

### `whatsapp_bot/conversation_store.py`

```python
@dataclass
class WaMessage:
    direction: str    # "inbound" / "outbound"
    timestamp: str    # ISO datetime string
    body: str

class ConversationStore:
    _MAX_MESSAGES = 20   # keep last 20 messages per number

    def add(self, phone: str, msg: WaMessage) -> None: ...
    def get_recent(self, phone: str, n: int = 10) -> list[WaMessage]: ...
```

Stored at `{DATA_DIR}/whatsapp/conversations.json`, keyed by phone number (digits only,
no `@c.us` suffix).

---

## Customer Profile (`customers/customer_store.py`)

New dataclass shared between the email agent and the WhatsApp bot:

```python
@dataclass
class PurchaseRecord:
    product_name: str
    purchase_date: str    # "YYYY-MM-DD"
    amount: float
    currency: str = "USD"
    status: str = "completed"  # completed / refunded / pending

@dataclass
class CustomerProfile:
    email: str                  # primary key
    name: str = ""
    whatsapp_number: str = ""   # E.164: "+8801XXXXXXXXX"
    company: str = ""
    customer_status: str = "active"   # active / lapsed / prospect
    tags: list = field(default_factory=list)
    notes: str = ""
    tone: str = ""
    wa_opted_in: bool = False   # must be True to receive proactive messages
    purchases: list = field(default_factory=list)   # list of PurchaseRecord dicts
```

`CustomerStore` follows the same pattern as `ContactStore`: JSON dict keyed by
`email.lower()`, with `upsert()`, `lookup()`, `list_all()`. Additional methods:
- `lookup_by_phone(phone)` — find customer by WhatsApp number
- `add_purchase(email, purchase)` — append a purchase record
- `list_by_status(status)` — segmentation queries for campaigns

---

## WhatsApp Prompt Design

WhatsApp messages are conversational — shorter and less formal than email:

```
You are a WhatsApp customer service assistant for [Company].
Reply in 1-3 short sentences. Casual and direct.
Do NOT include a greeting line or sign-off.

Customer: Ahmed Hassan (+8801XXXXXXXXX)
Last purchase: Mobile App Design — 2026-02-10 ($800)
Tags: e-commerce, design-client

Recent WhatsApp conversation (last 5 messages):
  [them] Hi, I wanted to ask about your new services
  [us]   We just launched a new dashboard package...
  [them] Sounds interesting, what's the price?

Their message: "Can you send me the details?"

Reply (1-3 sentences, no greeting, no sign-off):
```

---

## Example Conversations

### Inbound: Customer inquiry
```
Customer: "Do you still do UI design?"
Bot:      "Yes! We have Starter ($300), Professional ($800), and
           Enterprise ($2000+). Want details on a specific tier?"
Customer: "Tell me about the Professional one"
Bot:      "Professional covers wireframes, 5 screens, and 2 revision
           rounds. Want to book a 15-minute call to discuss your project?"
```

### Outbound: Re-engagement (opt-in customers only)
```
Bot:      "Hi Ahmed, it's been 4 months since your mobile design project.
           We launched a web dashboard add-on that pairs well with what
           you built — want to know more?"
Customer: "Sure, what's it cost?"
Bot (AI): [continues with purchase history and context]
```

### Human escalation
```python
_ESCALATION_KEYWORDS = {
    "refund", "angry", "not working", "disappointed", "urgent", "cancel"
}

if any(kw in body.lower() for kw in _ESCALATION_KEYWORDS):
    # Send email to team
    # Reply to customer: "I'm connecting you with our team — they'll be in touch shortly."
```

---

## Setup (One-Time)

1. Install Node.js (free, one-time, from nodejs.org)
2. `cd whatsapp_bridge && npm install`
3. `node index.js` — a QR code appears in the terminal
4. Open WhatsApp on the business phone → Linked Devices → Link a Device → scan QR
5. Done — the session is saved to `.wwebjs_auth/` and persists across restarts

The QR scan is required only once per machine. After that, `LocalAuth` reconnects
automatically.

---

## Integration with Existing Email Agent

| Shared resource | How used |
|---|---|
| `contacts.json` | Bot reads existing ContactProfile (read-only) |
| `interactions.json` | Bot reads email interaction history as extra context |
| `customers.json` | Bot reads/writes; email agent reads for campaign personalisation |
| `ReplyGenerator` | Bot instantiates its own instance (same code, same config, same LLM fallback) |
| `config.json` | Both services read persona prompt, knowledge base, tone settings |

---

## Cost

| Component | Cost |
|---|---|
| whatsapp-web.js | Free, open source |
| Node.js runtime | Free |
| Python bot service | Free (runs locally, same machine as email agent) |
| LLM via Groq fallback | Free tier (14,400 req/day) |
| **Total** | **$0 / month** |

---

## Known Limitations

| Limitation | Notes |
|---|---|
| Unofficial WhatsApp protocol | Low ban risk for legitimate business use; library is updated within days of WhatsApp protocol changes |
| Phone must be connected | Mirrors WhatsApp Web — the source phone must have an active internet connection |
| One active session per number | Same constraint as WhatsApp Web — only one linked device at a time |
| No read receipt API | Cannot programmatically confirm delivery or read status |
| Outbound opt-in required | Only send proactive messages to customers who have explicitly opted in (`wa_opted_in = True`). Sending unsolicited messages at scale risks the phone number being flagged by WhatsApp |

---

## Implementation Order (when ready to build)

1. `customers/customer_store.py` — CustomerProfile + PurchaseRecord + CustomerStore
2. `storage/app_config.py` — add `get_customers_path()`, `get_whatsapp_path()`
3. `whatsapp_bridge/package.json` + `index.js` — Node.js bridge
4. `whatsapp_bot/conversation_store.py` — per-number conversation history
5. `whatsapp_bot/bot_bridge.py` — HTTP client to Node.js
6. `whatsapp_bot/bot_daemon.py` — message handler + AI generation
7. `whatsapp_bot/routes/webhook.py` — POST /wa/incoming
8. `whatsapp_bot/routes/broadcast.py` — POST /wa/send
9. `whatsapp_bot/app.py` — Flask factory (port 5002)
10. Update `launcher.py` to optionally start the Node.js bridge process

---

## npm Dependencies

```json
{
  "dependencies": {
    "whatsapp-web.js": "^1.23.0",
    "express": "^4.18.0",
    "axios": "^1.6.0",
    "qrcode-terminal": "^0.12.0"
  }
}
```

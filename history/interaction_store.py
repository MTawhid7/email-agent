"""
Persistent per-contact interaction history.

Records a compact summary of each sent reply so future generations can
reference what was discussed with a recurring contact.  Stored as JSON
at {DATA_DIR}/history/interactions.json.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

_MAX_PER_CONTACT = 10   # keep last N interactions per contact


@dataclass
class InteractionRecord:
    thread_id: str
    date: str               # "YYYY-MM-DD"
    subject: str
    summary: str            # AI-generated summary of their email
    our_reply_summary: str  # AI-generated summary of the reply we sent
    topics: list = field(default_factory=list)   # 3-5 extracted topic tags


class InteractionStore:
    """
    JSON-backed store of recent interactions per contact email address.
    Thread-safe for single-writer / multiple-reader access via atomic writes.
    """

    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._save({})

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, email: str, interaction: InteractionRecord) -> None:
        """
        Prepend a new interaction for this contact and trim to the cap.
        Called once when the user clicks Send Now or Save as Draft.
        """
        data = self._load()
        key = email.lower().strip()
        records = data.get(key, [])
        records.insert(0, asdict(interaction))
        data[key] = records[:_MAX_PER_CONTACT]
        self._save(data)

    def get_recent(self, email: str, n: int = 5) -> list[InteractionRecord]:
        """Return the last n interactions with this contact, newest first."""
        data = self._load()
        records = data.get(email.lower().strip(), [])[:n]
        return [self._make(r) for r in records]

    def get_topics(self, email: str) -> list[str]:
        """Return deduplicated topic tags seen across all stored interactions."""
        data = self._load()
        records = data.get(email.lower().strip(), [])
        seen: set[str] = set()
        topics: list[str] = []
        for rec in records:
            for tag in rec.get("topics", []):
                tag = tag.strip().lower()
                if tag and tag not in seen:
                    seen.add(tag)
                    topics.append(tag)
                    if len(topics) >= 20:
                        return topics
        return topics

    # ── Internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make(record: dict) -> InteractionRecord:
        return InteractionRecord(
            thread_id=record.get("thread_id", ""),
            date=record.get("date", ""),
            subject=record.get("subject", ""),
            summary=record.get("summary", ""),
            our_reply_summary=record.get("our_reply_summary", ""),
            topics=record.get("topics", []),
        )

    def _load(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        tmp.replace(self._path)

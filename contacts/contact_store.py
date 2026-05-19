import json
import os
from dataclasses import asdict, dataclass
from typing import Optional

_DEFAULT_PATH = "contacts/contacts.json"


@dataclass(frozen=True)
class ContactProfile:
    email: str
    name: str = ""
    company: str = ""
    relationship_type: str = ""
    notes: str = ""


class ContactStore:
    """
    JSON-backed store for contact profiles, keyed by email address.
    The file is read fresh on every lookup to prevent stale data in the
    long-running daemon process.
    """

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._ensure_file()

    def lookup(self, email: str) -> Optional[ContactProfile]:
        """Return the ContactProfile for the given email, or None if not found."""
        data = self._load()
        record = data.get(email.lower())
        if record is None:
            return None
        return ContactProfile(**record)

    def upsert(self, profile: ContactProfile) -> None:
        """Create or fully replace the profile for profile.email."""
        data = self._load()
        data[profile.email.lower()] = asdict(profile)
        self._save(data)

    def list_all(self) -> list[ContactProfile]:
        """Return all stored profiles sorted by email."""
        data = self._load()
        return sorted(
            [ContactProfile(**v) for v in data.values()],
            key=lambda p: p.email,
        )

    # ── Private ────────────────────────────────────────────────────────────────

    def _ensure_file(self) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        if not os.path.exists(self._path):
            self._save({})

    def _load(self) -> dict:
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

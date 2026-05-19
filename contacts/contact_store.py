import json
import os
from dataclasses import asdict, dataclass, fields as dataclass_fields
from typing import Optional

_DEFAULT_PATH = "contacts/contacts.json"


@dataclass(frozen=True)
class ContactProfile:
    email: str
    name: str = ""
    company: str = ""
    relationship_type: str = ""
    notes: str = ""
    tone: str = ""   # Formal / Professional / Casual / Brief — overrides global persona


class ContactStore:
    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._ensure_file()

    def lookup(self, email: str) -> Optional[ContactProfile]:
        data = self._load()
        record = data.get(email.lower())
        if record is None:
            return None
        return self._make(record)

    def upsert(self, profile: ContactProfile) -> None:
        data = self._load()
        data[profile.email.lower()] = asdict(profile)
        self._save(data)

    def list_all(self) -> list[ContactProfile]:
        data = self._load()
        return sorted(
            [self._make(v) for v in data.values()],
            key=lambda p: p.email,
        )

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def _make(record: dict) -> ContactProfile:
        """Construct ContactProfile, ignoring unknown keys for backward compatibility."""
        known = {f.name for f in dataclass_fields(ContactProfile)}
        return ContactProfile(**{k: v for k, v in record.items() if k in known})

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

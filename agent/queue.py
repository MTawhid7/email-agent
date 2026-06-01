import threading
from datetime import datetime


class ReviewQueue:
    """Thread-safe in-memory queue for generated replies awaiting user action."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, dict] = {}

    def push(self, item: dict) -> None:
        with self._lock:
            self._items[item["id"]] = item

    def get(self, item_id: str) -> dict | None:
        with self._lock:
            return self._items.get(item_id)

    def remove(self, item_id: str) -> None:
        with self._lock:
            self._items.pop(item_id, None)

    def all(self) -> list[dict]:
        with self._lock:
            return sorted(self._items.values(), key=lambda x: x["created_at"], reverse=True)

    def count(self) -> int:
        with self._lock:
            return len(self._items)


# Module-level singleton shared between daemon and routes
review_queue = ReviewQueue()

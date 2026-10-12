"""Mémoire des promos déjà notifiées (fichier JSON commité par GitHub Actions)."""

import json
from datetime import date, timedelta
from pathlib import Path

# Au-delà, une entrée est oubliée : la promo est forcément terminée.
RETENTION_DAYS = 60


class SeenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, str] = {}
        if path.exists():
            self._seen = json.loads(path.read_text(encoding="utf-8"))

    def __contains__(self, uid: str) -> bool:
        return uid in self._seen

    def add(self, uids: list[str], today: date) -> None:
        for uid in uids:
            self._seen.setdefault(uid, today.isoformat())

    def save(self, today: date) -> None:
        cutoff = (today - timedelta(days=RETENTION_DAYS)).isoformat()
        kept = {uid: seen for uid, seen in self._seen.items() if seen >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(kept, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")

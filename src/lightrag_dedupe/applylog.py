"""``apply-log.jsonl``: one JSON line per finished or failed merge, so a rerun can resume."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .plan import Merge


def merge_key(merge: Merge) -> str:
    """Stable id of a merge (target + sorted sources), independent of the group id."""
    raw = json.dumps([merge.target, sorted(merge.sources)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ApplyLog:
    """Append-only log. Unreadable lines are ignored so a damaged log never blocks a rerun."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def done_keys(self) -> set[str]:
        keys: set[str] = set()
        if not self.path.is_file():
            return keys
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict) and entry.get("status") == "done" and isinstance(entry.get("key"), str):
                keys.add(entry["key"])
        return keys

    def record(self, merge: Merge, status: str, detail: str = "") -> None:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "id": merge.id,
            "key": merge_key(merge),
            "target": merge.target,
            "sources": list(merge.sources),
            "status": status,
        }
        if detail:
            entry["detail"] = detail
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

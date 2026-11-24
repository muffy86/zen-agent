"""zen-agent — portable memory: newline-delimited JSON, no database, no lock-in."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class MemoryStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: Dict[str, Any]) -> Dict[str, Any]:
        record = {"ts": event.pop("ts", None) or datetime.now(timezone.utc).isoformat(), **event}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        return record

    def read(self, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return [json.loads(ln) for ln in lines[-limit:]]

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Cheap lexical recall: events mentioning the query words, most recent first."""
        words = [w for w in query.lower().split() if len(w) > 2]
        hits = [e for e in self.read(500) if any(w in json.dumps(e).lower() for w in words)]
        return list(reversed(hits[-limit:]))

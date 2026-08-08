"""Section 4: "Every run logs reasoning + decision to a file — not just
the final action, so a bad trade is traceable back through the chain
afterward." One log file per chain run, one entry per role, written
incrementally as each role completes (not buffered until PM finishes) so a
crash mid-chain still leaves a partial trail.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes.config import Paths


@dataclass
class RoleLogEntry:
    role: str
    model: str
    reasoning: str
    output: Any
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RunLogger:
    """One instance per chain run. `run_id` is a sortable timestamp-based
    id so `ls trading/logs/` reads chronologically.
    """

    def __init__(self, run_id: Optional[str] = None, paths: Optional[Paths] = None):
        self.paths = paths or Paths()
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
        self.paths.logs_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.paths.logs_dir / f"{self.run_id}.jsonl"

    def log_role(self, entry: RoleLogEntry) -> None:
        with self.log_path.open("a") as f:
            f.write(json.dumps(entry.__dict__) + "\n")

    def log_event(self, event: str, detail: str) -> None:
        """Non-role events worth capturing in the same trail: limits
        rejections, gate checks, guard refusals.
        """
        entry = {
            "event": event,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def read_entries(self) -> list[dict]:
        if not self.log_path.exists():
            return []
        return [json.loads(line) for line in self.log_path.read_text().splitlines() if line.strip()]

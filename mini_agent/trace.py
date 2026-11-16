import json
import re
import time
import uuid
from pathlib import Path

_FORBIDDEN = ("..", "~", "\\")


class RunTrace:
    def __init__(self, base_dir=None):
        self.run_id = uuid.uuid4().hex[:8]
        self.base_dir = base_dir
        self.events = []

    def record(self, step, kind, **data):
        self.events.append({"step": step, "kind": kind, "ts": round(time.time(), 3), **data})

    def tool_events(self):
        return [e for e in self.events if e["kind"] in ("tool_call", "tool_result")]

    def to_lines(self):
        lines = []
        for event in self.events:
            rest = {k: v for k, v in event.items() if k not in ("step", "kind", "ts")}
            lines.append(f"[{event['step']:02d}] {event['kind']} {json.dumps(rest, ensure_ascii=False, default=str)}")
        return lines

    def _validated_root(self):
        raw = str(self.base_dir or "")
        if not raw or any(part in raw for part in _FORBIDDEN):
            raise ValueError("trace 目录不合法")
        root = Path(raw).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def save(self):
        root = self._validated_root()
        if not re.fullmatch(r"[0-9a-f]{8}", self.run_id):
            raise ValueError("run_id 不合法")
        path = (root / f"{self.run_id}.json").resolve()
        if not path.is_relative_to(root):
            raise ValueError("trace 文件路径越界")
        path.write_text(json.dumps(self.events, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)

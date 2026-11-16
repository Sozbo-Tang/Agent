import json
import time

from .utils import path_within, safe_name, tokenize


class MemoryStore:
    def __init__(self, directory, user_id, capacity=50):
        self.path = path_within(directory, safe_name(user_id) + ".json")
        self.capacity = capacity

    def _load(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, entries):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries[-self.capacity:], ensure_ascii=False, indent=2), encoding="utf-8")

    def remember(self, text):
        entries = self._load()
        entries.append({"text": text, "ts": time.time()})
        self._save(entries)

    def recall(self, query, k=3):
        tokens = set(tokenize(query))
        if not tokens:
            return []
        scored = []
        for index, entry in enumerate(self._load()):
            overlap = len(tokens & set(tokenize(entry.get("text", ""))))
            if overlap == 0:
                continue
            scored.append((overlap + (index + 1) / 100.0, entry.get("text", "")))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [text for _, text in scored[:k]]


def build_memory_block(entries):
    if not entries:
        return ""
    lines = "\n".join(f"- {entry}" for entry in entries)
    return f"以下是关于该用户的长期记忆，回答时可参考：\n{lines}"

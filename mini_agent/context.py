import json

from .utils import estimate_tokens

DEFAULT_SYSTEM_PROMPT = (
    "你是一个乐于助人的中文助手，可以调用工具完成任务：数学计算用 calculator；"
    "记录或查询待办用 todo；查资料用 search；查天气用 weather。"
    "需要工具时先调用工具，拿到结果后再回答；不需要时直接简洁地回答用户。"
)


class ContextManager:
    def __init__(self, budget, keep_recent, summarizer=None):
        self.budget = budget
        self.keep_recent = keep_recent
        self.summarizer = summarizer

    def build(self, session, memory_block=""):
        self.compress(session)
        history = session.pending_api_messages()
        system = self._system_prompt(session.summary, memory_block)
        budget_left = self.budget - estimate_tokens(json.dumps(system, ensure_ascii=False))
        kept = []
        total = 0
        for message in reversed(history):
            cost = estimate_tokens(json.dumps(message, ensure_ascii=False))
            if kept and total + cost > budget_left:
                break
            kept.append(message)
            total += cost
        kept.reverse()
        index = 0
        while index < len(kept) - 1 and kept[index].get("role") != "user":
            index += 1
        kept = kept[index:]
        return [system] + kept

    def compress(self, session):
        history = session.pending_api_messages()
        if len(history) <= self.keep_recent:
            return
        if self._tokens(history) <= int(self.budget * 0.7):
            return
        cut = len(history) - self.keep_recent
        while cut < len(history) and history[cut].get("role") != "user":
            cut += 1
        if cut >= len(history):
            return
        older = history[:cut]
        session.summary = self._merge_summary(session.summary, self._summarize(older))
        session.summarized_upto += cut

    def _summarize(self, messages):
        if self.summarizer is None:
            return "（早期对话过长，已整体省略，只保留了最近的消息）"
        transcript = "\n".join(json.dumps(m, ensure_ascii=False) for m in messages)
        return self.summarizer(transcript)

    def _merge_summary(self, old, new):
        if old:
            return f"{old}\n{new}"
        return new

    def _system_prompt(self, summary, memory_block):
        parts = [DEFAULT_SYSTEM_PROMPT]
        if summary:
            parts.append(f"当前会话此前的对话摘要：\n{summary}")
        if memory_block:
            parts.append(memory_block)
        return {"role": "system", "content": "\n\n".join(parts)}

    def _tokens(self, messages):
        return sum(estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)

import json
import uuid
from dataclasses import dataclass, field


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    raw_arguments: str
    error: str = None


@dataclass
class ParsedOutput:
    content: str = None
    thinking: str = None
    tool_calls: list = field(default_factory=list)

    @property
    def answer(self):
        if self.tool_calls:
            return None
        return self.content


def parse_message(message):
    thinking = message.get("reasoning_content") or message.get("reasoning") or None
    content = message.get("content") or None
    calls = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        raw = function.get("arguments")
        arguments, error = _parse_arguments(raw)
        calls.append(
            ToolCall(
                id=item.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=function.get("name") or "",
                arguments=arguments,
                raw_arguments=raw if isinstance(raw, str) else json.dumps(raw or {}, ensure_ascii=False),
                error=error,
            )
        )
    return ParsedOutput(content=content, thinking=thinking, tool_calls=calls)


def _parse_arguments(raw):
    if raw is None or raw == "":
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return {}, f"arguments 不是合法 JSON：{exc}"
    if not isinstance(parsed, dict):
        return {}, "arguments 必须是 JSON 对象"
    return parsed, None

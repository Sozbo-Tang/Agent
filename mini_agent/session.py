import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .parser import ToolCall
from .utils import path_within, safe_name


@dataclass
class Message:
    role: str
    content: str = None
    thinking: str = None
    tool_calls: list = field(default_factory=list)
    tool_call_id: str = None
    name: str = None

    def to_api(self):
        if self.role == "assistant" and self.tool_calls:
            return {
                "role": "assistant",
                "content": self.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.raw_arguments or "{}"},
                    }
                    for call in self.tool_calls
                ],
            }
        if self.role == "tool":
            return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content or ""}
        return {"role": self.role, "content": self.content or ""}

    def to_dict(self):
        return {
            "role": self.role,
            "content": self.content,
            "thinking": self.thinking,
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "tool_calls": [
                {
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments,
                    "raw_arguments": call.raw_arguments,
                    "error": call.error,
                }
                for call in self.tool_calls
            ],
        }

    @classmethod
    def from_dict(cls, data):
        calls = [
            ToolCall(
                id=item["id"],
                name=item["name"],
                arguments=item.get("arguments") or {},
                raw_arguments=item.get("raw_arguments") or "{}",
                error=item.get("error"),
            )
            for item in data.get("tool_calls") or []
        ]
        return cls(
            role=data["role"],
            content=data.get("content"),
            thinking=data.get("thinking"),
            tool_calls=calls,
            tool_call_id=data.get("tool_call_id"),
            name=data.get("name"),
        )


@dataclass
class Session:
    user_id: str
    session_id: str
    messages: list = field(default_factory=list)
    summary: str = ""
    summarized_upto: int = 0
    updated_at: float = 0.0

    def append(self, message):
        self.messages.append(message)
        self.updated_at = time.time()
        return message

    def append_user(self, text):
        return self.append(Message(role="user", content=text))

    def append_assistant(self, parsed):
        return self.append(
            Message(role="assistant", content=parsed.content, thinking=parsed.thinking, tool_calls=list(parsed.tool_calls))
        )

    def append_assistant_text(self, text):
        return self.append(Message(role="assistant", content=text))

    def append_tool_result(self, call, result):
        return self.append(Message(role="tool", content=result, tool_call_id=call.id, name=call.name))

    def pending_api_messages(self):
        return [message.to_api() for message in self.messages[self.summarized_upto:]]

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "summary": self.summary,
            "summarized_upto": self.summarized_upto,
            "updated_at": self.updated_at,
            "messages": [message.to_dict() for message in self.messages],
        }

    @classmethod
    def from_dict(cls, data):
        session = cls(
            user_id=data["user_id"],
            session_id=data["session_id"],
            summary=data.get("summary", ""),
            summarized_upto=data.get("summarized_upto", 0),
            updated_at=data.get("updated_at", 0.0),
        )
        session.messages = [Message.from_dict(item) for item in data.get("messages", [])]
        return session


class SessionStore:
    def __init__(self, root):
        self.root = root

    def _path(self, user_id, session_id):
        return path_within(self.root, "sessions", safe_name(user_id), safe_name(session_id) + ".json")

    def get(self, user_id, session_id):
        path = self._path(user_id, session_id)
        if not path.exists():
            return Session(user_id=user_id, session_id=session_id)
        return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, session):
        path = self._path(session.user_id, session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(session.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def list_sessions(self, user_id):
        directory = Path(self.root) / "sessions" / safe_name(user_id)
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.json"))

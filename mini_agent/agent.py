import os
from dataclasses import dataclass

from .context import ContextManager
from .llm import LLMError
from .memory import MemoryStore, build_memory_block
from .parser import parse_message
from .session import SessionStore
from .tools import ToolContext, ToolError
from .trace import RunTrace
from .utils import truncate


@dataclass
class AgentReply:
    answer: str
    session_id: str
    steps: int
    stopped_reason: str
    trace: RunTrace


class Agent:
    def __init__(self, llm, registry, config, session_store=None):
        self.llm = llm
        self.registry = registry
        self.config = config
        self.sessions = session_store or SessionStore(config.data_dir)
        self.memory_dir = os.path.join(config.data_dir, "memory")
        self.trace_dir = os.path.join(config.data_dir, "logs")

    def run(self, user_input, user_id, session_id):
        trace = RunTrace(self.trace_dir)
        session = self.sessions.get(user_id, session_id)
        memory = MemoryStore(self.memory_dir, user_id)
        memory_block = build_memory_block(memory.recall(user_input))
        session.append_user(user_input)
        context = ContextManager(self.config.context_budget, self.config.keep_recent, self.llm.summarize)
        answer = ""
        reason = "done"
        step = 0
        for step in range(1, self.config.max_steps + 1):
            messages = context.build(session, memory_block)
            trace.record(step, "llm_call", messages=len(messages))
            try:
                message = self.llm.chat(messages, self.registry.specs())
            except LLMError as exc:
                trace.record(step, "llm_error", error=str(exc))
                answer = f"模型调用失败：{exc}"
                reason = "error"
                break
            parsed = parse_message(message)
            trace.record(
                step,
                "assistant",
                thinking=truncate(parsed.thinking, 80) if parsed.thinking else None,
                tool_calls=[call.name for call in parsed.tool_calls],
            )
            if not parsed.tool_calls:
                session.append_assistant(parsed)
                answer = parsed.answer or ""
                break
            session.append_assistant(parsed)
            tool_context = ToolContext(user_id=user_id, session_id=session_id)
            for call in parsed.tool_calls:
                trace.record(step, "tool_call", name=call.name, arguments=call.arguments)
                try:
                    result = self.registry.invoke(call, tool_context)
                except ToolError as exc:
                    result = f"工具调用失败：{exc}"
                trace.record(step, "tool_result", name=call.name, result=truncate(result, 200))
                session.append_tool_result(call, result)
        else:
            answer = "这一轮的工具调用次数达到上限，我先停在这里，你可以继续追问或换个说法。"
            reason = "max_steps"
            session.append_assistant_text(answer)
        if reason == "done":
            memory.remember(truncate(f"用户：{user_input}；结论：{answer}", 160))
        self.sessions.save(session)
        trace.record(step, "run_finished", reason=reason, answer=truncate(answer, 120))
        return AgentReply(
            answer=answer,
            session_id=session_id,
            steps=step,
            stopped_reason=reason,
            trace=trace,
        )

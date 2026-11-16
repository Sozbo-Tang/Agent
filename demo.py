import json
import shutil

from mini_agent import Agent, build_default_registry, load_config


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.last_system = None

    def chat(self, messages, tools=None):
        self.last_system = messages[0]["content"]
        return self.responses.pop(0)

    def summarize(self, text):
        return "（演示摘要：更早的对话已压缩成这一句）"


def tool_reply(call_id, name, arguments):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        ],
    }


def text_reply(content):
    return {"role": "assistant", "content": content}


def show(reply, user, session, question):
    print(f"\n=== 用户 {user} / 会话 {session} ===")
    print(f"用户：{question}")
    for event in reply.trace.events:
        if event["kind"] == "tool_call":
            print(f"  · 调用工具 {event['name']}({event['arguments']})")
        elif event["kind"] == "tool_result":
            print(f"  · 工具返回 {event['result']}")
    print(f"Agent：{reply.answer}")


def main():
    data_dir = ".demo_data"
    shutil.rmtree(data_dir, ignore_errors=True)
    config = load_config()
    config.data_dir = data_dir
    llm = ScriptedLLM(
        [
            tool_reply("c1", "todo", {"action": "add", "title": "明天下午开评审会"}),
            text_reply("已记下：明天下午开评审会。"),
            tool_reply("c2", "calculator", {"expression": "(35+7)*4"}),
            text_reply("(35+7)*4 = 168。"),
            text_reply("周报可以这么写：本周完成了评审会安排，并推进了数据核对。"),
            tool_reply("c3", "todo", {"action": "list"}),
            text_reply("你还有一条待办：明天下午开评审会。"),
            text_reply("根据我的记忆，你明天下午要开评审会。"),
        ]
    )
    agent = Agent(llm, build_default_registry(data_dir), config)

    questions = [
        ("alice", "窗口1", "帮我记住明天下午开评审会"),
        ("alice", "窗口1", "顺便算一下 (35+7)*4"),
        ("alice", "窗口2", "我在写周报，帮我总结一句"),
        ("alice", "窗口1", "我的待办有哪些"),
    ]
    for user, session, question in questions:
        show(agent.run(question, user, session), user, session, question)

    print("\n=== 新开会话，验证跨会话记忆 ===")
    show(agent.run("我明天有什么安排", "alice", "新会话"), "alice", "新会话", "我明天有什么安排")
    recalled = [line for line in llm.last_system.splitlines() if "评审会" in line]
    print(f"新会话的 system prompt 里召回了记忆：{recalled}")

    print("\n=== 每个窗口一份独立的会话文件 ===")
    for name in agent.sessions.list_sessions("alice"):
        session = agent.sessions.get("alice", name)
        first_user = next((m.content for m in session.messages if m.role == "user"), "")
        print(f"- {name}：{len(session.messages)} 条消息，第一句是「{first_user}」")


if __name__ == "__main__":
    main()

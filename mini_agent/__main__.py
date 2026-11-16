import argparse
import os

from .agent import Agent
from .config import load_config
from .llm import LLMError, OpenAICompatibleClient
from .tools import build_default_registry

HELP = """可用命令：
  /switch <名字>   切换到另一个会话窗口
  /sessions        列出当前用户的所有会话
  /help            显示这份帮助
  /exit            退出"""


def main():
    parser = argparse.ArgumentParser(description="一个从零实现的最小 Agent")
    parser.add_argument("--user", default="me", help="用户名，同一用户的待办和记忆共享")
    parser.add_argument("--session", default="main", help="会话名，不同会话互相独立")
    parser.add_argument("--verbose", action="store_true", help="显示思考过程和工具结果")
    args = parser.parse_args()

    config = load_config()
    try:
        llm = OpenAICompatibleClient(config)
    except LLMError as exc:
        print(exc)
        print("示例：export LLM_API_KEY=你的key LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4 LLM_MODEL=glm-4.6")
        return

    agent = Agent(llm, build_default_registry(config.data_dir), config)
    user, session = args.user, args.session
    print(f"已连接 {config.model}，当前用户 {user}，会话 {session}，数据目录 {os.path.abspath(config.data_dir)}")
    print(HELP)
    while True:
        try:
            line = input(f"[{session}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line == "/exit":
            break
        if line.startswith("/switch"):
            parts = line.split()
            if len(parts) == 2:
                session = parts[1]
                print(f"已切换到会话 {session}")
            else:
                print("用法：/switch <名字>")
            continue
        if line == "/sessions":
            names = agent.sessions.list_sessions(user)
            if names:
                for name in names:
                    print(f"- {name}")
            else:
                print("还没有历史会话")
            continue
        if line == "/help":
            print(HELP)
            continue
        reply = agent.run(line, user, session)
        for event in reply.trace.events:
            if event["kind"] == "tool_call":
                print(f"  · 调用工具 {event['name']}({event['arguments']})")
            elif event["kind"] == "tool_result" and args.verbose:
                print(f"  · 工具结果 {event['result']}")
            elif event["kind"] == "assistant" and args.verbose and event.get("thinking"):
                print(f"  · 思考 {event['thinking']}")
        prefix = "  ×" if reply.stopped_reason == "error" else "  ⇢"
        print(f"{prefix} {reply.answer}")
        reply.trace.save()


if __name__ == "__main__":
    main()

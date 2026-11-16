import ast
import hashlib
import json
import operator
import time
from dataclasses import dataclass
from datetime import date

from .utils import path_within, safe_name, tokenize


class ToolError(Exception):
    pass


@dataclass
class ToolContext:
    user_id: str
    session_id: str


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: object


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        self._tools[tool.name] = tool

    def get(self, name):
        return self._tools.get(name)

    def names(self):
        return sorted(self._tools)

    def specs(self):
        return [
            {
                "type": "function",
                "function": {"name": tool.name, "description": tool.description, "parameters": tool.parameters},
            }
            for tool in self._tools.values()
        ]

    def invoke(self, call, context):
        tool = self.get(call.name)
        if tool is None:
            raise ToolError(f"没有叫 {call.name} 的工具，可用工具：{'、'.join(self.names())}")
        if call.error:
            raise ToolError(call.error)
        try:
            return tool.handler(call.arguments, context)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"{tool.name} 执行出错：{exc}") from exc


_BINARY_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _eval_node(node):
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ToolError("指数太大，拒绝计算")
        return _BINARY_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise ToolError("表达式里包含不支持的运算或符号")


def calculator(arguments, context):
    expression = arguments.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise ToolError("需要提供字符串参数 expression")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"表达式无法解析：{exc.msg}") from exc
    result = _eval_node(tree)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{expression} = {result}"


_SEARCH_CORPUS = [
    ("Agent Loop 的最小实现", "一个 agent 主循环通常由感知、决策、行动组成，模型输出工具调用，执行后把结果拼回上下文继续推理。"),
    ("Function Calling 约定", "OpenAI 兼容接口里，模型通过 tool_calls 字段发起调用，工具结果用 role 为 tool 的消息回传给模型。"),
    ("上下文压缩的常用做法", "对话过长时可以把早期消息总结成一条摘要，保留最近若干轮原文，兼顾记忆与上下文预算。"),
    ("待办事项管理小技巧", "把事项写下来并标注优先级，完成后立刻勾掉，能显著减少任务切换的成本。"),
    ("广州与厦门的天气特点", "广州夏季湿热多雷雨，厦门临海昼夜温差小，春秋两季最舒适。"),
    ("GLM 系列模型接口", "智谱开放平台的 chat completions 接口兼容 OpenAI 协议，支持 tools 参数、流式输出与深度思考。"),
]


def search(arguments, context):
    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolError("需要提供字符串参数 query")
    tokens = set(tokenize(query))
    scored = []
    for title, snippet in _SEARCH_CORPUS:
        overlap = len(tokens & set(tokenize(title + snippet)))
        if overlap:
            scored.append((overlap, title, snippet))
    if not scored:
        return f"没有找到与「{query}」相关的结果"
    scored.sort(key=lambda item: item[0], reverse=True)
    lines = []
    for rank, (_, title, snippet) in enumerate(scored[:3], 1):
        lines.append(f"[{rank}] {title}：{snippet}")
    return "\n".join(lines)


_WEATHER_CITIES = ["北京", "上海", "广州", "深圳", "厦门", "杭州", "成都", "武汉"]
_CONDITIONS = ["晴", "多云", "阴", "小雨", "雷阵雨"]


def weather(arguments, context):
    city = arguments.get("city")
    if not isinstance(city, str) or not city.strip():
        raise ToolError("需要提供字符串参数 city")
    if city not in _WEATHER_CITIES:
        return f"暂无 {city} 的天气数据，目前支持：{'、'.join(_WEATHER_CITIES)}"
    seed = f"{city}:{date.today().isoformat()}"
    digest = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    condition = _CONDITIONS[digest % len(_CONDITIONS)]
    temperature = 12 + digest % 20
    humidity = 40 + digest % 50
    advice = "适合出门" if temperature >= 18 else "出门注意保暖"
    return f"{city}今天{condition}，气温 {temperature}°C，湿度 {humidity}%，{advice}"


class TodoStore:
    def __init__(self, directory, user_id):
        self.path = path_within(directory, safe_name(user_id) + ".json")

    def load(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, items):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, title):
        items = self.load()
        items.append({"title": title, "done": False, "created_at": time.strftime("%Y-%m-%d %H:%M")})
        self.save(items)
        return len(items)

    def complete(self, target):
        items = self.load()
        index = self._locate(items, target)
        items[index]["done"] = True
        self.save(items)
        return items[index]["title"]

    def _locate(self, items, target):
        if isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
            index = int(target) - 1
            if 0 <= index < len(items):
                return index
            raise ToolError(f"没有编号为 {target} 的待办")
        for index, item in enumerate(items):
            if isinstance(target, str) and target and target in item["title"]:
                return index
        raise ToolError(f"没有找到和「{target}」相关的待办")

    def render(self):
        items = self.load()
        if not items:
            return "当前没有待办事项"
        lines = []
        for index, item in enumerate(items, 1):
            mark = "x" if item["done"] else " "
            lines.append(f"{index}. [{mark}] {item['title']}")
        return "\n".join(lines)


def _make_todo_tool(data_dir):
    def handler(arguments, context):
        store = TodoStore(data_dir + "/todos", context.user_id)
        action = arguments.get("action")
        if action == "add":
            title = arguments.get("title")
            if not isinstance(title, str) or not title.strip():
                raise ToolError("add 操作需要 title 参数")
            title = title.strip()
            count = store.add(title)
            return f"已添加待办「{title}」，当前共 {count} 条"
        if action == "complete":
            target = arguments.get("target", arguments.get("title"))
            if target in (None, ""):
                raise ToolError("complete 操作需要待办编号或标题")
            return f"已完成待办「{store.complete(target)}」"
        if action == "list":
            return store.render()
        raise ToolError("action 只支持 add、complete、list")

    return Tool(
        name="todo",
        description="管理用户的待办事项，数据按用户持久保存，跨会话可用",
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "complete", "list"], "description": "要执行的操作"},
                "title": {"type": "string", "description": "add 时为待办内容，complete 时可用来匹配待办"},
                "target": {"type": "string", "description": "complete 时的待办编号或标题，可省略"},
            },
            "required": ["action"],
        },
        handler=handler,
    )


def build_default_registry(data_dir):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="calculator",
            description="计算四则运算和幂运算，输入一个数学表达式字符串，返回精确结果",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "数学表达式，例如 (1+2)*3"}},
                "required": ["expression"],
            },
            handler=calculator,
        )
    )
    registry.register(
        Tool(
            name="search",
            description="搜索资料库并返回最相关的几条结果（离线演示数据）",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
            handler=search,
        )
    )
    registry.register(
        Tool(
            name="weather",
            description="查询指定城市当天的天气",
            parameters={
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名，例如 厦门"}},
                "required": ["city"],
            },
            handler=weather,
        )
    )
    registry.register(_make_todo_tool(data_dir))
    return registry

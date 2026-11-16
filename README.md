# mini-agent

一个从零实现的最小可用 Agent：不依赖任何 agent 框架（langgraph / openhands 等），主循环、工具注册、输出解析、session 管理、context 压缩、跨会话 memory 全部手写，只通过 HTTP 调用任意 OpenAI 兼容的 chat completions 接口。

## 题目要求对照

| 要求 | 实现 | 位置 |
| --- | --- | --- |
| 基本循环（输入→判断→工具→循环或返回） | `Agent.run` 的 for 循环，每步先构建 context、调模型、解析、按需执行工具 | `mini_agent/agent.py` |
| 至少三个工具，todo 必须有 | calculator / search（离线 mock）/ weather（确定性 mock）/ todo（按用户持久化） | `mini_agent/tools.py` |
| 工具注册机制（名称、描述、参数 Schema） | `ToolRegistry.register / specs`，Schema 直接下发给模型的 `tools` 参数 | `mini_agent/tools.py` |
| LLM 输出解析（思考 / 工具调用 / 最终答案） | `parse_message` 提取 `reasoning_content` 思考、`tool_calls`、纯文本答案 | `mini_agent/parser.py` |
| 独立 session，随时接着聊 | 按 `(user_id, session_id)` 落盘 JSON，窗口互不干扰 | `mini_agent/session.py` |
| 最大轮次限制 | `AGENT_MAX_STEPS`，超过后优雅收尾并补一条 assistant 消息 | `mini_agent/agent.py` |
| 记住之前状态、支持追问（纯对话 / 带工具） | 完整 history 回放，工具调用与结果都在 context 里 | `mini_agent/agent.py` + 测试 |
| context 过长的基础压缩 | 超预算时把早期消息摘要成一条 system 摘要，保留最近若干轮原文 | `mini_agent/context.py` |
| 异常处理 / 工具 trace | LLM 网络重试、工具错误回喂模型、每步事件落盘 `.data/logs/` | `mini_agent/trace.py` |
| 测试用例 | 47 个用例，FakeLLM 脚本化模型回复，全程离线 | `tests/` |

## 快速开始

需要 Python 3.9+。依赖只有 `requests`（调用真实模型时）和 `pytest`：

```bash
pip install -r requirements.txt
```

### 1. 离线演示（不需要 API key）

```bash
python3 demo.py
```

用脚本化的假模型跑完双窗口隔离、待办持久化、跨会话记忆召回的完整流程，适合先看效果。

### 2. 接真实模型

API key 只从环境变量读取，**代码和仓库里不会出现任何密钥**：

```bash
export LLM_API_KEY=你的key
export LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
export LLM_MODEL=glm-4.6
python3 -m mini_agent --user alice --session work
```

换供应商只需要换环境变量，例如 DeepSeek：

```bash
export LLM_BASE_URL=https://api.deepseek.com/v1
export LLM_MODEL=deepseek-chat
```

CLI 内命令：`/switch <名字>` 切换会话窗口、`/sessions` 列出历史会话、`/exit` 退出；加 `--verbose` 可以看到思考过程和完整工具结果。

### 3. 双窗口验证

开两个终端（或一个终端里用 `/switch`）：

```bash
python3 -m mini_agent --user alice --session window1
python3 -m mini_agent --user alice --session window2
```

窗口 1 让 Agent 查天气记待办，窗口 2 让它写周报记待办，两边各自接着聊，历史互不串。同一用户的 todo 和长期记忆是共享的（这是用户级数据，不是会话级），测试里对两种语义都有断言。

### 4. 跑测试

```bash
python3 -m pytest tests -v
```

47 个用例全部离线运行，不需要网络和 API key。

## 配置项

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_API_KEY` | 无（必填） | 模型服务密钥，只从环境读取 |
| `LLM_BASE_URL` | `https://open.bigmodel.cn/api/paas/v4` | 任意 OpenAI 兼容服务，必须是 https 公网地址 |
| `LLM_MODEL` | `glm-4.6` | 模型名 |
| `LLM_TIMEOUT` | `60` | 单次请求超时（秒） |
| `AGENT_MAX_STEPS` | `8` | 单轮对话里模型的最大循环步数 |
| `AGENT_CONTEXT_BUDGET` | `6000` | 上下文预算（粗略 token 估算，按 3 字符 ≈ 1 token） |
| `AGENT_KEEP_RECENT` | `6` | 压缩时始终保留的最近消息条数 |
| `AGENT_DATA_DIR` | `.data` | 数据落盘目录 |

## 系统设计

```
            ┌────────────────────────── CLI (python -m mini_agent) ─────────────────────────┐
            │                                                                                │
 用户输入 ──► Agent.run ──► ContextManager.build ──► messages ──► OpenAICompatibleClient ──► 模型
            │    ▲                │    ▲                                  │                   │
            │    │           MemoryStore.recall（长期记忆注入 system）        │ message           │
            │    │                │                                      ▼                   │
            │ SessionStore    Session.summary（会话内摘要注入 system）  parse_message           │
            │    │                │                              ┌───────┴────────┐          │
            │    │                ▼                              │ 有 tool_calls  │ 纯文本    │
            │    │        超预算时把早期消息压缩成摘要              │       ▼        │    ▼      │
            │    │                                              │ ToolRegistry   │ 返回用户  │
            │    │                                              │   .invoke      │          │
            │    │                                              │       ▼        │          │
            │    └──────────── tool 结果追加进 history ◄─────────┘  RunTrace 记录每一步       │
            └────────────────────────────────────────────────────────────────────────────────┘
```

### 主循环

对应题目的四步：

1. 接收用户输入：追加到 `(user_id, session_id)` 对应的 Session history。
2. 判断直接回复还是调工具：把注册表生成的工具 Schema 随 messages 一起发给模型，`tool_choice=auto`，由模型自主决策；`parse_message` 解析返回。
3. 调用工具：`ToolRegistry.invoke` 执行，异常统一转成 `工具调用失败：...` 文本，作为 `role=tool` 消息回喂。
4. 判断继续还是返回：有工具调用就把结果追加进 history 进入下一轮；纯文本即最终答案，写入 session、写入 memory 后返回。

循环上限由 `AGENT_MAX_STEPS` 控制。达到上限时不会让 history 悬空停在工具结果上，而是补一条 assistant 收尾消息，保证下一轮请求的消息序列仍然合法。

### 工具注册机制

每个工具是一个 `Tool(name, description, parameters, handler)`，`parameters` 是 JSON Schema；`registry.specs()` 负责转成接口需要的 `tools` 格式。新增一个工具只要：

```python
registry.register(
    Tool(
        name="read_docs",
        description="读取项目文档",
        parameters={
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
        handler=lambda args, ctx: f"文档内容：{args['filename']}",
    )
)
```

calculator 用 AST 白名单求值（只放行四则运算、幂和数字节点），杜绝 `eval` 注入；todo 的 handler 通过 `ToolContext.user_id` 把数据落到用户自己的文件，天然实现按用户隔离。

### Session 管理

- 存储：`.data/sessions/{user}/{session}.json`，每个文件是完整 history + 会话摘要 + 压缩水位线（`summarized_upto`）。
- 隔离：窗口 = session_id，读取时按 key 加载，互不可见；同一用户换个窗口等于换个文件。
- 恢复：进程重启后 `SessionStore.get` 直接从磁盘读回，随时接着聊。
- 文件名经过 `safe_name` 白名单清洗（保留 Unicode 字母数字、`-`、`_`），`../` 之类不可能逃出数据目录。

### Context 管理

哪些信息进入 context（我的取舍）：

| 信息 | 是否进入 | 原因 |
| --- | --- | --- |
| 用户输入 | 是 | 追问的锚点 |
| assistant 的工具调用请求 | 是 | 模型要知道自己上一步做了什么 |
| 工具执行结果 | 是 | 带工具追问（"把刚才的结果乘 3"）依赖它 |
| assistant 思考过程（reasoning_content） | 只存不回传 | 推理链对后续轮次价值低、token 开销大，业界（GLM `clear_thinking`、DeepSeek）同样不建议回传 |
| 工具的原始返回超大时 | 截断到 200 字符进 trace | 防止单个工具结果吃掉整个预算 |
| 长期记忆 / 会话摘要 | 是，注入 system | 见下文 Memory 一节 |

压缩策略（`ContextManager`）：

1. 未压缩 history 的估算 token 超过预算 70% 且条数多于 `keep_recent` 时触发；
2. 切点从"倒数第 keep_recent 条"开始，向后对齐到下一条 user 消息，保证不会把 assistant 的工具调用和对应的工具结果切开（否则会产生悬空的 `role=tool` 消息，接口会报错）；
3. 切点之前的消息交给模型摘要（`llm.summarize`），追加到 `session.summary`，并推进 `summarized_upto` 水位线——已摘要的部分不会重复摘要；
4. 摘要注入 system prompt；无摘要能力时退化为占位说明 + 保留最近消息，功能不中断。

追问能力来自第 1、2 行那张表：纯对话追问靠完整 history 回放；带工具追问靠工具调用与结果都在 context 里，模型能直接引用 `3+5*2 = 13` 这类中间结论。测试里分别有 `test_followup_sees_previous_tool_result` 等用例覆盖。

### Memory：召回时机与放置方式

这是本次实现里唯一超出"会话内记忆"的部分，设计刻意保持简单（关键词 + 时序，不引 embedding）：

| 问题 | 决策 |
| --- | --- |
| 写入时机 | 每轮 `run` 成功结束后，把 `用户：输入；结论：答案` 截断到 160 字存入该用户的 memory 文件；容量 50 条，满了丢最旧 |
| 召回时机 | 每次 `run` 开始、构建 context 之前，用**当前这条用户输入**做召回——这是模型马上要用记忆的时刻，且拿得到最相关的查询词 |
| 召回方式 | 当前输入分词（英文词 + 中文二元组）后与每条记忆算重叠数，重叠 > 0 才入选，按 重叠数 + 新近程度 排序取 top 3 |
| 放置方式 | 拼成"以下是关于该用户的长期记忆"区块，追加在 **system prompt 末尾**（会话摘要在它前面）。放 system 而不是 user，是因为记忆是背景知识而非本轮指令，且不污染工具调用的消息配对 |
| 为什么不塞全量记忆 | 长期记忆是召回制的：相关才注入，无关时 system 里不出现该区块（测试断言过），避免每轮浪费预算 |

升级路线（没在本题实现）：向量检索召回、按重要性衰减打分、读写都过一遍小模型提炼——对应 mem0 / Letta 那一层的记忆框架。

### 异常处理与 Trace

| 失败场景 | 行为 |
| --- | --- |
| 网络错误 / 5xx / 429 | 重试一次（间隔 1s），仍失败则本轮返回错误说明，history 保留用户消息，下次可续 |
| 4xx（key 错、参数错） | 不重试，直接报错给用户 |
| 工具抛异常 / 参数不是合法 JSON / 工具不存在 | 转成 `工具调用失败：...` 文本回喂模型，模型可以改参数重试或直接回答 |
| 达到最大步数 | 优雅收尾 + 补 assistant 消息，用户可继续追问 |
| CLI Ctrl+C / EOF | 正常退出 |

每轮对话的完整 trace（llm_call / assistant / tool_call / tool_result / llm_error / run_finished）既随 `AgentReply` 返回给调用方，也落盘 `.data/logs/{run_id}.json`；CLI 默认打印工具调用行，`--verbose` 再加思考与结果。

## 数据落盘布局

```
.data/
├── sessions/{user}/{session}.json   每窗口一份完整历史 + 摘要 + 水位线
├── todos/{user}.json                用户级待办，跨会话共享
├── memory/{user}.json               用户级长期记忆，最多 50 条
└── logs/{run_id}.json               每轮执行 trace
```

## 测试说明

| 文件 | 覆盖点 |
| --- | --- |
| `test_parser.py` | 思考提取、工具调用解析（字符串/字典参数）、坏 JSON 标记不抛异常、缺 id 自动生成 |
| `test_tools.py` | 计算器优先级/幂/除零/注入拦截、todo 增删查与用户隔离、搜索排序与空结果、天气确定性、Schema 结构、未知工具 |
| `test_session.py` | 双窗口隔离、落盘往返（含 tool_calls）、文件名清洗、摘要水位线持久化 |
| `test_context.py` | 预算内不压缩、摘要触发与水位线稳定、无摘要降级、裁剪不产生悬空 tool 消息、记忆进 system |
| `test_memory.py` | 关键词召回、无关查询不召回、容量淘汰、用户隔离 |
| `test_agent.py` | 直答 / 工具 / 追问 / 窗口隔离 / 待办跨会话 / 最大步数 / 工具错误回喂 / 模型失败恢复 / 记忆召回 / trace 顺序 |

模型行为全部由 `FakeLLM` 按脚本回放，同时它记录每次收到的 messages，测试可以精确断言"模型看到了什么"。

## 设计取舍与已知限制

- search / weather 是确定性 mock（题目允许），换成真实 API 只需替换 handler。
- token 估算用字符数近似（3 字符 ≈ 1 token），不引 tokenizer 依赖，预算控制是粗粒度的。
- memory 是关键词召回，同义词问法（"明天有啥安排"vs"日程"）可能漏召回，取舍见上一节。
- 只支持原生 function calling 协议；不支持模型在纯文本里输出 JSON 动作的降级协议。
- `LLM_BASE_URL` 做了 https + 公网校验（拒绝环回 / 内网 / 链路本地 / 保留地址），因此不能用本机 Ollama 调试，这是防 SSRF 的刻意取舍。

## 提交物清单

- 源码：`mini_agent/`（约 900 行，含类型标注，无第三方 agent 依赖）
- 测试：`tests/`（47 个用例，`python3 -m pytest tests -v`）
- 离线演示：`demo.py`
- 说明文档：本 README
- AI Prompt 与问题解决记录：[PROMPTS.md](PROMPTS.md)

# AI Prompt 与问题解决记录

开发全程允许 AI 辅助，这里如实记录关键 prompt、AI 的贡献和我做的判断。总体原则：AI 负责查资料、出方案选项、挑毛病；架构取舍和每行进仓库的代码由我把关。

## 1. 调研阶段

### Prompt 1：确认主循环的事实标准

> 搜一下 Anthropic「Building Effective Agents」和主流 minimal agent 开源实现，一个不依赖框架的最小 agent 主循环到底长什么样？哪些是必须的，哪些是框架带来的多余抽象？

结论（[Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)）：

- 事实标准就是"一个 while/for 循环 + LLM 调用 + 工具执行"，Anthropic 原文也建议从最简单的 loop 起步，编排层是后加的；
- 必须件：消息历史、工具 Schema 下发、模型输出解析、工具结果回喂；多余抽象：图编排、多 agent 路由、重状态机。

落地：`Agent.run` 就是一个 for 循环，for-else 处理"步数耗尽"分支，没有引入任何调度结构。

### Prompt 2：确认消息协议细节

> OpenAI 兼容接口里工具结果怎么回传？assistant 带 tool_calls 的消息和 role=tool 消息有什么配对要求？GLM 的思考模型输出是什么字段？

结论（[OpenAI function calling 指南](https://developers.openai.com/api/docs/guides/function-calling)、[智谱 OpenAI 兼容文档](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)）：

- 工具结果必须是 `role=tool` + `tool_call_id`，和 assistant 的 tool_calls 逐条配对；
- 思考过程在 `reasoning_content`（GLM/DeepSeek 风格），多轮回传它价值低开销大，智谱甚至有 `clear_thinking` 参数专门丢弃它。

落地：`parser.parse_message` 三路解析（思考 / 工具调用 / 最终答案）；history 里存 thinking 但 `to_api` 不回传。

## 2. 设计阶段的关键取舍

### Prompt 3：calculator 怎么做才安全

> LLM 让工具执行用户传来的数学表达式，直接 eval 有代码注入风险，Python 里安全的做法是什么？

AI 给了两条路：正则白名单字符 + eval，或者 ast.parse 白名单节点递归求值。我选了后者：只放行 `Expression / Constant / BinOp / UnaryOp` 加七种运算符节点，顺带加了幂指数上限防止 `9**9**9**9` 卡死。测试里专门有 `__import__('os')...` 的注入用例。

### Prompt 4：压缩切点不能切在哪

> 把历史消息摘要压缩时，如果切点正好落在 assistant(tool_calls) 和 role=tool 之间会发生什么？

AI 指出会产生"悬空的 tool 消息"，OpenAI 兼容接口会直接 400。这是我最初实现里真实存在的 bug 隐患。修复：切点向后对齐到下一条 user 消息；`build` 的兜底裁剪同样对齐；最大步数收尾时补一条 assistant 文本消息。三处防悬空，`test_context.py` 和 `test_agent.py` 各有断言。

### Prompt 5：memory 召回的时机和放置

> 最小实现里的跨会话记忆，召回放在什么时机、注入到哪个位置最合理？不想引 embedding。

AI 列了三种植入点：拼进当前 user 消息、单独 system 消息、追加在主 system prompt 末尾。我选了第三种：记忆是背景知识不是本轮指令，放 system 末尾既不干扰指令区，也不破坏 user/tool 消息配对；召回时机定在"每次 run 开始、构建 context 前"，因为那一刻才拿得到本轮输入做相关性查询。README 有专节论述。

## 3. 编码与调试阶段踩的坑

### 坑 1：我自己写错了期望值

test_agent 里我断言 `3+5*2 = 16`，跑出来 13，第一反应是计算器优先级错了——复查发现是**我的测试断言错了**（5*2=10，3+10=13，计算器是对的）。这个案例正好说明了为什么测试期望值要手算两遍。修正断言后全绿。

### 坑 2：中文会话名被清洗成 "1"

`safe_name` 最初只允许 `[0-9A-Za-z_-]`，demo 里"窗口1"落盘成了 `1`，两个窗口差点撞名。改成 Unicode `\w` 白名单（保留中文，依然拦 `/`、`..`、`:`），中文会话名可读性保住，路径穿越依然不可能。

### 坑 3：本地安全扫描逼出来的加固

开发中本地安全扫描（Mimosa）拦了几次提交，虽然多数是误报倾向的规则，但修完确实让代码更稳，索性记录下来：

| 扫描发现 | 修复 |
| --- | --- |
| 文件写入路径穿越风险 | 所有落盘路径统一走 `safe_name` 白名单 + `path_within`（resolve 后 `is_relative_to` 包含校验），`open()` 一律换 pathlib 的 `read_text/write_text` |
| md5 弱哈希 | weather 的确定性种子从 md5 换成 sha256 |
| 动态 URL 的 SSRF 风险 | `_guard_outbound_url`：强制 https、拒绝环回/内网/链路本地/保留地址（DNS 解析后校验 IP），代价是没法连本机 Ollama，README 已声明是刻意取舍 |
| registry.execute 误报 SQL 注入 | 改名 `invoke`，语义也更贴切 |

### 坑 4：FakeLLM 要记录"模型看到了什么"

测试断言追问能力时，光看返回答案不够——要证明第二轮请求的 messages 里真的带着第一轮的工具结果。所以 `FakeLLM` 会深拷贝并保存每次收到的 messages，`test_followup_sees_previous_tool_result` 直接对它断言 `"计算结果是 13。" in json.dumps(messages)`，比断言最终答案可信得多。

## 4. 我和 AI 的分工边界

- AI：查协议细节、给方案选项、解释报错、review 边界条件（悬空 tool 消息就是它抓的）。
- 我：定模块边界和消息流、决定"思考过程只存不回传"、决定 memory 的召回时机与放置、审查每一处安全修复是否值得做、手算所有测试期望值、跑通 47 个用例。

## 5. 参考资料

- [Anthropic: Building Effective Agents](https://www.anthropic.com/research/building-effective-agents)
- [Anthropic: Writing Effective Tools for AI Agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [OpenAI: Function calling 指南](https://developers.openai.com/api/docs/guides/function-calling)
- [智谱开放平台：OpenAI 兼容接口](https://docs.bigmodel.cn/cn/guide/develop/openai/introduction)
- [ai-agent-starter（150 行无框架 agent）](https://github.com/spinov001-art/ai-agent-starter)

> From: https://claude.ai/chat/36782e2c-1444-413b-8cc2-162ae308da6a

# you asked

可以安排一份学习AI agent的路线吗，最主要是给我一些AI agent项目分析，我去看高手是怎么做的

---

# claude response

好的。先说一下我的思路：看高手的 agent 项目，最怕一上来就扎进几万行的框架代码，很容易迷路。比较好的顺序是**从最小的循环开始，一层层往上加复杂度**。每加一层，就去看一个在这一层做得最好的项目。

所有 agent 的骨架其实都一样：**LLM + 循环 + 工具 + 上下文管理**。下面每个阶段都是在这个骨架上回答一个新问题。

---

## 阶段 0：建立心智模型（1–2 天）

**读这两篇**
- Anthropic 的 *Building Effective Agents*：重点区分 workflow（流程由代码写死）和 agent（流程由模型决定），还有五种常见模式：prompt chaining、routing、parallelization、orchestrator-workers、evaluator-optimizer。
- ReAct 论文（Reason + Act）：几乎所有 agent 循环的源头。

**带着这个问题读**：我之前做的项目，哪些部分其实是 workflow，哪些才是真正的 agent？很多"agent"其实是 workflow，这并不是坏事。

---

## 阶段 1：最小 agent 循环

**项目 1：mini-swe-agent**（SWE-agent 团队出的极简版）
- 核心逻辑大约 100 行，只给模型一个工具：bash。
- 看什么：循环是怎么写的、什么时候停、模型输出怎么解析成动作、错误怎么喂回给模型。
- 值得思考的点：只有一个 bash 工具也能在 SWE-bench 上拿到不错的分数，说明工具"少而通用"有时比"多而专"更好。

**项目 2：smolagents**（Hugging Face）
- 看 `CodeAgent` 和 `ToolCallingAgent` 的对比：前者让模型直接写 Python 代码当作动作，后者用 JSON 调用工具。
- 思考：用代码当动作有什么好处（可以组合、可以写循环），又有什么风险（需要沙箱）？

**练习**：看完后不要用框架，自己写一个 50 行左右的 agent 循环，只接一个工具。这一步对理解后面所有项目最关键。

---

## 阶段 2：工具设计与上下文工程（高手功力最集中的地方）

**项目 3：SWE-agent**
- 核心概念是 ACI（Agent-Computer Interface）：工具是给 LLM 用的，不是给人用的，所以要重新设计。
- 看什么：它的文件查看器为什么一次只显示 100 行、编辑命令为什么自带 lint 检查、搜索结果为什么要截断。每一个设计都在解决"模型会犯什么错"。

**项目 4：Aider**
- 看 **repo map**：用 tree-sitter 抽出整个代码库的函数和类签名，按重要性排序，再压进有限的上下文。
- 看 **edit format**：为什么用 search/replace 块而不是让模型重写整个文件。
- 思考：上下文窗口有限的时候，"给模型看什么"本身就是一个算法问题。

---

## 阶段 3：架构、状态与可控性

**项目 5：OpenHands**
- 看 event stream 架构：所有 action 和 observation 都是事件，agent controller 负责调度，runtime 跑在 Docker 沙箱里。
- 思考：为什么要把"决策"和"执行环境"彻底分开？这对安全和回放有什么好处？

**项目 6：LangGraph**
- 看 state graph、checkpoint（可以暂停和恢复）、human-in-the-loop（在关键步骤停下来等人确认）。
- 思考：什么时候该把 agent 拆成显式的状态机，而不是放一个大循环让模型自己跑？

**项目 7：OpenAI Agents SDK**
- 很轻量，适合看三个概念：handoff（agent 之间交接任务）、guardrails（输入输出检查）、tracing（可观测性）。

---

## 阶段 4：记忆

**项目 8：Letta（原 MemGPT）**
- 核心想法：把上下文窗口当作内存，把外部存储当作硬盘，让模型自己调用工具去编辑记忆。
- 看什么：core memory 和 archival memory 是怎么分层的，模型什么时候决定把信息"换出"上下文。

---

## 阶段 5：Web3 agent（结合你的背景）

**项目 9：ElizaOS**
- 看插件体系里的三个概念：actions（能做什么）、providers（往上下文注入什么信息）、evaluators（对话后做什么反思）。
- 看 character 配置：人格和行为是怎么跟代码解耦的。

**项目 10：GOAT SDK / Coinbase AgentKit**
- 看它们怎么把链上操作（转账、swap、调用合约）抽象成 LLM 能用的工具，以及钱包是怎么接进来的。
- **重点思考安全问题**：私钥绝对不能进入模型的上下文；交易执行前要做模拟；要设置金额上限和白名单；还要防范 prompt injection，比如恶意代币名称或网页内容诱导 agent 转账。高手的项目和 demo 项目最大的区别，往往就在这里。

---

## 怎么读一个项目（通用方法）

1. **先跑起来**，给它一个简单任务。
2. **打开日志或 tracing**，看一次完整请求里，模型到底收到了什么 prompt、调用了哪些工具。这比读代码有用十倍。
3. **只追一条主路径**：从入口找到 agent 循环，再找到工具调用。其他代码先跳过。
4. **找 system prompt 和工具描述**：高手的很多经验都写在 prompt 里，而不是代码里。
5. **用自己的话写下来**：这个项目解决了什么问题，换成你会怎么做。

---

按你习惯的节奏，我建议从阶段 1 的 mini-swe-agent 开始：代码短，能完整看懂一个循环。要不要我们下一步一起拆它的核心文件，我一段一段讲给你听？

---

# you asked

好的，学习这些需要具备哪些前置条件呢，请详细介绍并给出相关的学习路线

---

# claude response

好问题。先给结论：**学 agent 不需要会训练模型，也不需要深度学习的数学。** 它更像是"用 LLM 做系统工程"。你已经有 Solidity、前端和 Python 数据处理的经验，大部分底子其实都有了。真正需要补的，主要是 LLM API 这一层。

下面按重要性排序，每一项都会说明为什么需要、学到什么程度算够，以及你大概处在什么位置。

---

## 一、真正的核心前置：LLM API 与工具调用（必须先学）

这是整条路线的地基。前面推荐的每一个项目，本质上都是在包装这一层。如果这层没吃透，看项目时会一直觉得"魔法在别处"。

**1. 对话的基本结构**
- messages 的角色：system、user、assistant。
- 模型本身是**无状态**的：每次请求都要把完整历史发过去。所谓"记忆"，其实就是你自己决定往历史里放什么。理解了这一点，你就能明白为什么 Aider 要做 repo map、Letta 要做记忆分层。
- token、上下文窗口、计费方式：你会发现 agent 的很多设计，都是在跟"上下文装不下"和"太贵"这两件事作斗争。

**2. Tool use / function calling（最关键）**
- 你用 JSON Schema 描述工具（名称、说明、参数）。
- 模型不会自己执行工具，它只返回"我想调用某个工具，参数是什么"。
- 你的代码负责执行，再把结果作为 tool result 发回去，模型接着往下想。
- **这个"请求 → 调用工具 → 返回结果 → 再请求"的往返，就是 agent 循环本身。**

**3. 其他需要了解的参数和功能**
- temperature：agent 一般调低，追求稳定。
- streaming 流式输出。
- structured output：让模型稳定输出 JSON。
- stop reason：模型是说完了，还是想调用工具，还是被截断了。agent 循环就是靠它判断要不要继续。
- prompt caching：长 system prompt 反复发送时能省很多钱。

**学到什么程度算够**：不用任何框架，只用官方 SDK，写出一个能调用两个工具（比如"查天气"和"做计算"）的多轮对话程序，并且能说清楚每一轮发出去和收回来的 JSON 长什么样。

**学习资源**：Anthropic 或 OpenAI 的官方文档里关于 tool use 的章节，以及官方 cookbook 里的例子。

---

## 二、编程语言

**Python（主力语言，大部分项目都用）**
你做过地理数据处理，基础语法应该没问题。需要重点补的是这几项：
- **async/await**：agent 经常要并发调用工具和处理流式输出，OpenHands、LangGraph 里到处都是异步代码。
- **类型注解和 Pydantic**：工具的参数 schema 通常就是用 Pydantic 模型自动生成的。看懂这一点，很多框架代码就不神秘了。
- **项目和依赖管理**：venv、uv 或 poetry。为了把开源项目跑起来，这些绕不开。

**TypeScript / Node（Web3 方向必需）**
ElizaOS、GOAT SDK、Coinbase AgentKit 主要是 TS 写的。你有前端经验，这块应该比较熟。需要注意的是 Node 端的异步模式，以及 monorepo 的结构（pnpm workspace），因为 ElizaOS 就是 monorepo，第一次看容易找不到入口。

---

## 三、工程基础设施

| 技能 | 为什么需要 | 学到什么程度 |
|---|---|---|
| Shell / Bash | mini-swe-agent 唯一的工具就是 bash；coding agent 都在跟终端打交道 | 能看懂常见命令、管道、退出码 |
| Git | 读源码、看 commit 历史理解设计演变；coding agent 本身也在操作 git | 熟练使用 log、diff、blame |
| Docker | OpenHands 的沙箱、各种 agent 的隔离执行环境 | 能写简单的 Dockerfile，理解容器和宿主机的隔离 |
| JSON Schema | 工具定义就是 JSON Schema | 看得懂 type、properties、required、enum |
| HTTP / REST | 工具经常就是在调 API | 你应该已经会了 |

---

## 四、概念性知识（边学项目边补也可以）

**1. Embedding 和向量检索（RAG）**
- 文本可以转成向量，语义相近的文本向量距离也近。
- 记忆系统（Letta）、文档问答、长期知识库都依赖它。
- 学到什么程度：知道 embedding 是什么、向量数据库在做什么、chunking（文本切块）为什么重要。不需要理解模型内部原理。

**2. Prompt engineering**
- 怎么写清晰的 system prompt、怎么给示例、怎么写工具描述。
- 前面提过，高手的很多经验藏在 prompt 和工具描述里。你得先知道好的 prompt 长什么样，才看得出别人的 prompt 好在哪里。

**3. 评估（Eval）**
- agent 的输出不确定，怎么知道改了 prompt 之后是变好还是变坏？
- 了解 SWE-bench 这类 benchmark 的思路，以及"准备一组测试任务，每次改动后跑一遍"这种基本做法。
- 这是业余项目和专业项目差距最大的地方之一。

**4. MCP（Model Context Protocol）**
- 一个让工具"即插即用"的开放协议：工具写成 MCP server，任何支持 MCP 的 agent 都能接入。
- 现在很多项目都在接 MCP，值得花半天看一下规范，再写一个最简单的 server。

---

## 五、特定项目需要的额外知识（遇到再学）

- **Aider**：抽象语法树（AST）和 tree-sitter 的基本概念，用来理解 repo map 是怎么抽取函数签名的。
- **LangGraph**：有限状态机和有向图的基本概念。
- **browser-use 这类浏览器 agent**：DOM 结构、Playwright。
- **Web3 agent**：你的强项，需要额外关注的是 agent 场景下的几件事：
  - 用 viem 或 ethers 程序化地构造和签名交易；
  - 交易模拟（`eth_call` 或 Tenderly 这类工具），在真正发送前先预演结果；
  - 账户抽象和 session key：给 agent 一个权限受限的钥匙，而不是主私钥。这是让链上 agent 安全落地的关键思路。

---

## 六、学习路线（按周安排，可以根据进度调整）

**第 1 周：LLM API 地基**
- 第 1–2 天：读官方文档里的 messages、tokens、system prompt 部分，用 SDK 写一个多轮聊天程序，亲手体会"无状态"：故意不传历史，看模型是不是"忘了"。
- 第 3–5 天：学 tool use，写出前面说的双工具程序。把每一轮请求和响应的 JSON 打印出来，逐个字段对照文档看懂。
- 第 6–7 天：加上 structured output 和 streaming。
- **自检问题**：模型是怎么"调用"工具的？（答案：它没有真的调用，只是输出了调用意图。）

**第 2 周：补齐 Python 异步和工程工具**
- async/await：写一个并发调用三个 API 的小程序，对比串行和并发的耗时。
- Pydantic：定义一个模型，导出它的 JSON Schema，你会发现它跟工具定义几乎一模一样。
- Docker：把第 1 周的程序装进容器里跑起来。

**第 3 周：概念补充 + 进入阶段 0 和阶段 1**
- 读 *Building Effective Agents* 和 ReAct。
- 半天学 embedding 基础，写一个最小的"文本存入 → 语义搜索"程序。
- 半天读 MCP 规范，写一个只有一个工具的 MCP server。
- 开始读 mini-swe-agent，然后自己写那个 50 行的 agent 循环。

**第 4 周以后：按上一份路线的阶段 2 → 5 推进**
遇到第五部分列出的特定知识，现学现用就好，不需要提前准备。

---

## 一个判断标准

当你能做到下面这件事，就说明前置条件已经够了：

> 不看任何框架，写一个 agent：它能读写本地文件、执行 shell 命令，循环运行直到完成一个小任务（比如"在这个目录里找到所有 TODO 注释，汇总成一个 markdown 文件"），并且你能解释每一行代码为什么存在。

做到这一步，再去看 OpenHands、LangGraph 这些大项目，你会发现它们只是在这个循环上加了状态管理、沙箱、记忆和可观测性，而不是什么全新的东西。

如果你愿意，我们可以从第 1 周的 tool use 开始，我先讲清楚一次工具调用往返里 JSON 的每个字段，然后你动手写，我帮你看。

---

# you asked

好的，请结合上述所有内容，给我相应学习的路线和链接，我通过AI辅助要在3周内完成

---

# claude response

下面把前两次的内容合并成一份 21 天的计划。先说明几个前提：

- **时间假设**：每天 3–4 小时。3 周很紧，所以每天分成"必做"和"可选"。时间不够就只做必做部分，路线依然完整。
- **取舍原则**：读项目只追主路径。框架只学核心概念，不追求全面掌握。
- **链接**：我核实了几个近期有变动的链接（文档域名、仓库改名等）。开源项目更新很快，如果某个链接打不开，到对应组织的 GitHub 主页找一下即可。

---

## AI 辅助的正确用法

- **让 AI 做的事**：解释看不懂的代码段、给你出自检题、review 你写的代码、帮你在大仓库里定位入口文件。读仓库时可以配合 DeepWiki（https://deepwiki.com），它会为 GitHub 仓库生成结构说明，适合第一次打开陌生项目时用。
- **必须自己做的事**：Day 3 的工具调用程序、Day 7 的最小 agent 循环、第 3 周的毕业项目，核心代码要自己写。这三处就是这份路线的"肌肉记忆"，交给 AI 写，就等于没学。
- **推荐的对话方式**：把读到的文件贴给我，先说出你自己的理解，我再纠正和补充。这比直接让我讲解效果好得多。

---

## 第 1 周：地基 + 第一个 agent

**Day 1｜心智模型**
- 必读：Anthropic《Building Effective Agents》https://www.anthropic.com/engineering/building-effective-agents
- 选读：ReAct 论文 https://arxiv.org/abs/2210.03629（看摘要和图 1 即可）
- 自检：五种 workflow 模式分别是什么？workflow 和 agent 的区别在哪？你之前做过的项目属于哪一种？

**Day 2｜LLM API 基础**
- 资料：Claude 文档 https://platform.claude.com/docs/en/overview（看 Messages API 和上下文窗口部分）
- 动手：用 Python SDK 写一个多轮对话程序。然后做一个实验：故意不传历史消息，亲眼看模型"失忆"。
- 自检：为什么说"记忆"是你的代码决定的，而不是模型自带的？

**Day 3｜工具调用（全路线最重要的一天）**
- 资料：Tool use 文档 https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview 。目录里有一篇手把手搭建工具调用 agent 的教程，还有定义工具、处理工具调用、并行工具调用等章节，按顺序读。
- 动手（自己写）：一个双工具程序（比如"计算"和"读取本地文件"），把每一轮请求和响应的完整 JSON 打印出来。
- 自检：`stop_reason` 有哪几种值？各自意味着循环该怎么走？

**Day 4｜工程补课**
- Pydantic：https://docs.pydantic.dev/latest/ 定义一个模型并导出 JSON Schema，跟 Day 3 的工具定义对比，你会发现几乎一样。
- asyncio：https://docs.python.org/3/library/asyncio.html 写一个并发请求三个 API 的小程序，对比串行和并发的耗时。
- Docker：https://docs.docker.com/get-started/ 把 Day 3 的程序装进容器跑起来。
- 选做：浏览 Claude Cookbooks https://github.com/anthropics/claude-cookbooks 。它按能力分类组织，包括工具调用、agent 模式（含子 agent）、RAG、提示缓存等，先看 `tool_use/` 目录。

**Day 5｜高手怎么设计工具和上下文**
- 必读：《Writing effective tools for agents》https://www.anthropic.com/engineering/writing-tools-for-agents
- 必读：《Effective context engineering for AI agents》https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- 自检：用自己的话写下 5 条"给 LLM 设计工具"的原则。回头看 Day 3 的工具，哪里可以改进？

**Day 6｜第一个高手项目：mini-swe-agent**
- 仓库：https://github.com/SWE-agent/mini-swe-agent
- 动手：先跑起来，给它一个简单任务，然后找到核心循环文件，逐行读懂。
- 重点看：循环什么时候停、模型输出怎么解析成命令、命令报错怎么喂回给模型。

**Day 7｜写自己的 agent + 第一周复盘**
- 动手（自己写）：不用任何框架，写一个约 50 行的 agent，工具只有 bash 或文件读写。任务示例："找出目录里所有 TODO 注释，汇总成 markdown 文件"。
- 必须包含：最大步数限制、工具报错时把错误信息返回给模型。
- 复盘：把你的代码跟 mini-swe-agent 对比，列出三处差异。

---

## 第 2 周：读高手项目

**Day 8｜smolagents：用代码当动作**
- 仓库：https://github.com/huggingface/smolagents
- 重点看：`CodeAgent` 和 `ToolCallingAgent` 的区别。
- 自检：让模型直接写 Python 代码作为动作，好处和风险分别是什么？

**Day 9｜SWE-agent：Agent-Computer Interface**
- 论文：https://arxiv.org/abs/2405.15793（重点读 ACI 设计章节）
- 仓库：https://github.com/SWE-agent/SWE-agent （看工具定义部分）
- 自检：它的文件查看器为什么限制显示行数？编辑命令为什么自带 lint？每个设计在防止模型犯什么错？

**Day 10｜Aider：上下文压缩**
- Repo map 原理：https://aider.chat/2023/10/22/repomap.html
- 仓库：https://github.com/Aider-AI/aider
- 重点看：repo map 怎么用 tree-sitter 抽取签名并排序，以及为什么用 search/replace 块来编辑文件，而不是重写整个文件。

**Day 11｜OpenHands：架构分层**
- 注意一个变化：OpenHands 现在是多仓库结构，主仓库 OpenHands/OpenHands 以 TypeScript 前端和控制中心为主，构建 agent 的模块化 Python SDK 单独放在 software-agent-sdk 仓库里。所以学 agent 核心，直接读 SDK：https://github.com/OpenHands/software-agent-sdk
- 重点看：事件流（action / observation）、决策和执行环境的分离、沙箱。
- 自检：把"大脑"和"手"分开，对安全和回放有什么好处？

**Day 12｜LangGraph：状态机与人工介入**
- 仓库：https://github.com/langchain-ai/langgraph
- 课程（选做）：LangChain Academy https://academy.langchain.com 的 LangGraph 入门课，只看前两个模块。
- 动手：用 LangGraph 重写 Day 7 的 agent，加一个"执行危险命令前暂停，等人确认"的节点。

**Day 13｜OpenAI Agents SDK + 评估**
- 仓库：https://github.com/openai/openai-agents-python 只看三个概念：handoffs、guardrails、tracing。
- 必读：《Demystifying evals for AI agents》https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- 动手：给 Day 7 的 agent 准备 5 个测试任务，写一个脚本批量跑，统计成功率。

**Day 14｜升级自己的 agent + 第二周复盘**
- 把这周学到的用上：工具输出截断（SWE-agent）、上下文压缩（Aider）、事件日志（OpenHands）、评估脚本（Day 13）。
- 复盘：用一页纸写下"五个项目各自最值得学的一个设计"。

---

## 第 3 周：记忆、MCP、Web3 与毕业项目

**Day 15｜Embedding 与记忆**
- 动手：用任意 embedding API 写一个最小的"文本存入 → 语义检索"程序，体会 chunking 对结果的影响。
- 论文：MemGPT https://arxiv.org/abs/2310.08560（看前两节和架构图）
- 仓库（选做）：https://github.com/letta-ai/letta
- 自检：core memory 和 archival memory 分别解决什么问题？

**Day 16｜MCP**
- 规范和教程：https://modelcontextprotocol.io
- 动手：写一个只有一个工具的 MCP server（比如查询某个地址的 ETH 余额），再接到 Claude Desktop 或你自己的 agent 上。
- 选读：《Code execution with MCP》https://www.anthropic.com/engineering/code-execution-with-mcp

**Day 17｜ElizaOS：Web3 agent 框架**
- 仓库：https://github.com/elizaOS/eliza 。运行时核心在 packages/core 里，包括 agent 循环、插件模型、消息/记忆/状态原语，从这里入手，不要从 app 目录开始读。
- 重点看：插件可以注册 actions、providers、evaluators、services 等。挑一个官方插件，搞清楚这三类概念分别在做什么。

**Day 18｜链上工具层 + 安全**
- GOAT SDK：https://github.com/goat-sdk/goat
- Coinbase AgentKit：https://github.com/coinbase/agentkit
- viem：https://viem.sh （复习交易构造和 `simulateContract`）
- 重点思考：私钥是怎么跟模型隔离的？如果是你，会加哪些防线？（交易模拟、金额上限、地址白名单、session key、防 prompt injection）

**Day 19–20｜毕业项目（自己写）**
做一个链上分析 agent，要求：
- 工具通过 MCP 提供（复用 Day 16 的成果）；
- 至少包含"查询余额 / 交易记录"和"模拟交易"两类工具；
- 第一版只读，不签名、不发送真实交易；
- 有最大步数、工具输出截断、事件日志；
- 用 Day 13 的方法写 5 个测试任务。

如果时间富余，再加一个带人工确认的 testnet 转账功能。

**Day 21｜收尾**
- 给毕业项目写 README：架构图、设计取舍、每个设计借鉴自哪个项目。
- 选读：《Effective harnesses for long-running agents》https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- 总复盘：回到 Day 1 的问题，重新回答"workflow 和 agent 怎么选"，对比你三周前的答案。

---

## 时间不够时的砍法

优先保留 Day 3、5、6、7、9、10、13、16、19–20，这几天是主干。Day 8、12、15、17 可以压缩成半天的浏览；所有标"选读 / 选做"的内容都可以跳过。

开始 Day 1 的时候，可以把你读完《Building Effective Agents》后对五种模式的理解发给我，我们从那里开始。

---

# you asked

不用，我有很多精力和时间，我必须要完成的，我不怕压力

---

# claude response

那就按全量版本来：所有标"选读 / 选做"的内容都改成必做，每周再加一组加练任务。

先说一句实话：3 周的瓶颈不是投入多少小时，而是理解有没有跟上。时间多的人最容易犯的错，是"读完了"但其实没懂。所以我给每天加了一个**通关标准**：达不到就不进入下一天，宁可当天多熬一会儿。这比单纯堆时长更能保证你真的学会。

---

## 每日节奏（6–8 小时版）

- **上午：读**。文档、论文、源码。边读边用自己的话记笔记。
- **下午：写**。当天的动手任务，核心代码自己写。
- **晚上：考**。把笔记和代码发给我，我出 3–5 道题考你，或者 review 你的代码。答不上来的地方，第二天上午优先补。

---

## 每天的通关标准

| 天 | 通关标准 |
|---|---|
| D1 | 不看资料，画出五种 workflow 模式的示意图，并各举一个 Web3 场景的例子 |
| D2 | 能解释"模型无状态"，并用实验结果证明 |
| D3 | 能对着打印出来的 JSON，逐字段解释一次工具调用往返 |
| D4 | Pydantic 模型导出的 schema 能直接当作工具定义使用 |
| D5 | 写出 5 条工具设计原则，并据此重构 D3 的工具 |
| D6 | 不看代码，复述 mini-swe-agent 的完整循环 |
| D7 | 自己的 agent 能稳定完成 TODO 汇总任务 |
| D8–13 | 每个项目写一段话："它解决了什么问题 + 最值得偷的一个设计" |
| D14 | 升级后的 agent 在 5 个测试任务上的成功率高于升级前 |
| D15–18 | 每个概念都有一段能跑的代码作为证明 |
| D19–21 | 毕业项目能通过全部测试任务，README 写清楚每个设计借鉴自哪里 |

---

## 加练任务（在主线完成后做）

**第 1 周**
- 用 OpenAI API 把 D3 的双工具程序再实现一遍，对比两家 tool use 协议的差异（消息结构、工具结果怎么回传、并行调用怎么表示）。
- 给 D7 的 agent 加上流式输出，让你能实时看到模型的思考和工具调用。

**第 2 周**
- 在自己的 agent 里实现一个简化版 repo map：用 Python 的 `ast` 模块抽取函数和类签名，压缩后放进上下文。
- 让 mini-swe-agent 跑几个 SWE-bench Lite 的任务，读它的完整轨迹，找出它在哪一步走了弯路。
- 写一篇对比笔记：mini-swe-agent、SWE-agent、Aider、OpenHands 四者在"工具设计"和"上下文管理"上各自的取舍。

**第 3 周**
- 给毕业项目实现 MemGPT 式的自编辑记忆：让 agent 用工具自己决定什么信息存入长期记忆。
- 把毕业项目的核心能力包装成一个 ElizaOS 插件，体会框架化前后的区别。
- testnet 转账功能做完整：交易模拟、金额上限、地址白名单、人工确认，有余力再加 session key。
- 把项目开源到 GitHub，写一个技术 thread 讲清楚设计思路。讲得出来，才说明真的懂了。

---

## 留一个缓冲

建议把第 14 天晚上和第 21 天上午空出来作为缓冲。不是休息，而是用来补前面没通关的部分。高强度计划几乎一定会有某一天卡住，提前留出补救的位置，整体节奏就不会崩。

---

现在就可以开始 Day 1。读完《Building Effective Agents》后，不要发总结给我，直接做通关题：凭记忆画出（或用文字描述）五种模式的结构，并给每种模式举一个 Web3 场景的例子，比如"用 routing 把用户的链上查询分发到不同的处理流程"。发给我之后，我来判断你过没过关。

---

# you asked

还有前置条件的学习计划你安排好了吗

---

# claude response

安排了一部分，但没有完全安排好。之前的 21 天计划把核心前置（LLM API、工具调用、Python 异步、Pydantic、Docker、embedding、MCP）都嵌进了具体的天数里，但还有几项前置没有落到具体日期上，比如 Shell、Git、JSON Schema、prompt engineering、TypeScript 工程化、AST。下面把它补完整。

---

## 一、前置条件 → 安排在哪一天

| 前置条件 | 安排位置 | 状态 |
|---|---|---|
| LLM API 基础（messages、token、无状态） | D2 | 已安排 |
| 工具调用 | D3 | 已安排 |
| structured output、streaming、prompt caching | D3–D4 | 原计划只提了一句，**现在补到 D4** |
| Python 异步、Pydantic | D4 | 已安排 |
| Docker | D4 | 已安排 |
| JSON Schema | — | **新增到 D3 上午** |
| Prompt engineering | — | **新增到 D5** |
| Shell / Bash、Git | — | **新增到 Day 0** |
| AST / tree-sitter | — | **新增到 D10 上午** |
| 状态机、有向图 | D12 顺带 | 概念简单，读 LangGraph 时顺便理解 |
| 评估方法 | D13 | 已安排 |
| Embedding / RAG | D15 | 已安排 |
| MCP | D16 | 已安排 |
| TypeScript 工程化（monorepo、bun） | — | **新增到 D16 晚上** |
| viem、交易模拟、session key | D18 | 已安排 |

---

## 二、新增的 Day 0：前置自检 + 工程工具补课

在 Day 1 之前加一天。你的背景已经覆盖了很多内容，没必要从零学。Day 0 的目的是**先测出缺口，只补缺的部分**。

**上午：自检。** 下面每一项，能做到就打勾跳过，做不到就当天补：

1. Shell：能看懂 `grep -rn "TODO" . | wc -l` 每一部分在做什么，知道命令的退出码是什么、怎么查看。
2. Git：会用 `git log --oneline`、`git diff`、`git blame` 来追踪某一行代码是谁、在什么时候、为什么改的。
3. Python：能写一个带类型注解的 dataclass，知道 `async def` 和普通函数的区别（细节留到 D4 学）。
4. TypeScript：能看懂泛型、interface、`async/await`，以及 `import type` 的用法。
5. JSON：能手写一个包含嵌套对象和数组的 JSON，并知道怎么校验格式是否正确。

**下午：补课（按自检结果选）。**
- Shell 和 Git：MIT 的 *The Missing Semester* https://missing.csail.mit.edu ，看 Shell、Shell Tools、Version Control 三讲。这门课专门讲"学校不教但工程必需"的工具，非常适合这里。
- Git 深入（可选）：*Pro Git* https://git-scm.com/book 的第 2、3 章。
- TypeScript：官方 Handbook https://www.typescriptlang.org/docs/handbook/ 。你有前端经验，跳读即可。

**通关标准**：用 `git blame` 和 `git log` 在任意一个开源仓库里找到某个函数最近一次修改的 commit，并用一句话说清楚那次改动的原因。D9–D11 读源码时会反复用到这个技能。

---

## 三、插入到原有天数的补充

**D3 上午加：JSON Schema（约 1 小时）**
- 教程：https://json-schema.org/learn/getting-started-step-by-step
- 掌握 `type`、`properties`、`required`、`enum`、`description` 就够了。其中 `description` 最重要，因为模型就是靠它理解工具和参数的。

**D4 加：Claude API 的三个进阶功能**
- 在 Claude 文档 https://platform.claude.com/docs/en/overview 的侧边栏里找到 structured outputs、streaming、prompt caching 三部分。
- 动手：让模型稳定输出一个符合 Pydantic schema 的 JSON；把 D2 的对话程序改成流式输出。

**D5 加：Prompt engineering**
- 资料：https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- 跟当天的两篇工程博客一起读，你会发现"写好工具描述"和"写好 prompt"其实是同一种能力。

**D10 上午加：AST 基础（约 1.5 小时）**
- Python `ast` 文档：https://docs.python.org/3/library/ast.html
- tree-sitter：https://tree-sitter.github.io/tree-sitter/
- 动手：用 Python 的 `ast` 模块解析一个 `.py` 文件，打印出所有函数名和参数。这同时也是第 2 周加练"简化版 repo map"的第一步。

**D16 晚上加：为 ElizaOS 做准备**
- Bun 文档：https://bun.sh/docs ，了解 `bun install`、`bun run` 和 workspace 的基本用法。
- 动手：在本地 clone ElizaOS 并成功安装依赖，确保 D17 一早就能直接读代码，而不是卡在环境配置上。

---

## 四、更新后的整体结构

- **Day 0**：前置自检 + 工程工具补课
- **D1–D7**：LLM API 地基 + 第一个 agent（含 JSON Schema、structured output、prompt engineering）
- **D8–D14**：读高手项目（含 AST）
- **D15–D21**：记忆、MCP、Web3、毕业项目（含 TypeScript 工程化准备）

总共 22 天，前置条件已经全部落到具体日期上了。

现在可以从 Day 0 的自检开始。做完后把五项的结果告诉我，哪些打勾、哪些没过，我帮你调整当天下午的补课内容。

---

# you asked

给我全部安排好再给我

---

# claude response

下面是合并后的完整版，共 22 天（Day 0 到 Day 21）。所有内容都是必做，不再区分选做；加练任务已经分配到具体日期，缓冲时间也已排好。

---

# 总则

**每日节奏（6–8 小时）**
- 上午：读。文档、论文、源码，边读边用自己的话记笔记。
- 下午：写。当天的动手任务，核心代码自己写。
- 晚上：考。把笔记和代码发给我，我出题考你或者 review 代码。答不上来的地方，第二天上午优先补。

**通关规则**
每天都有一个通关标准，达不到就不进入下一天。宁可当天多花时间，也不要带着没弄懂的地方往前走。

**AI 辅助规则**
- 可以让 AI 做：解释代码段、出自检题、review 代码、在大仓库里定位入口文件。读陌生仓库时，可以先用 DeepWiki（https://deepwiki.com）看一遍结构。
- 必须自己写：D3 的工具调用程序、D7 的最小 agent、D15 的记忆模块、D19–D20 的毕业项目。
- 提问方式：先说出你自己的理解，再让 AI 纠正。

**缓冲时间**
- D14 晚上、D21 上午：用来补前面没通关的部分。没有欠账的话，就提前开始后面的内容。

**链接说明**
开源项目更新很快。如果某个链接打不开，到对应组织的 GitHub 主页找一下即可。

---

# Day 0｜前置自检 + 工程工具

**上午：自检。** 每项能做到就跳过，做不到就下午补：
1. Shell：看懂 `grep -rn "TODO" . | wc -l` 每一部分的作用，知道退出码是什么、怎么查。
2. Git：会用 `git log --oneline`、`git diff`、`git blame`。
3. Python：能写带类型注解的 dataclass，知道 `async def` 和普通函数的区别。
4. TypeScript：看得懂泛型、interface、`async/await`、`import type`。
5. JSON：能手写嵌套对象和数组，并知道怎么校验格式。

**下午：补课（按自检结果选）。**
- *The Missing Semester*：https://missing.csail.mit.edu （Shell、Shell Tools、Version Control 三讲）
- *Pro Git*：https://git-scm.com/book （第 2、3 章）
- TypeScript Handbook：https://www.typescriptlang.org/docs/handbook/

**晚上：** 把自检结果发给我。

**通关标准：** 在任意开源仓库里，用 `git log` 和 `git blame` 找到某个函数最近一次修改的 commit，用一句话说清楚改动原因。

---

# 第 1 周：地基 + 第一个 agent

### Day 1｜心智模型
- **上午：**
  - 《Building Effective Agents》：https://www.anthropic.com/engineering/building-effective-agents
  - ReAct 论文全文：https://arxiv.org/abs/2210.03629
- **下午：** Anthropic 的演讲《How We Build Effective Agents》：https://ai.engineer/talks/effective-ai-agents 。演讲里提出了判断是否值得做 agent 的检查清单：任务复杂度够高、价值撑得起 token 成本、关键能力已经验证过、错误容易被发现；还建议站在 agent 的视角，只看它那有限的上下文窗口来思考问题。
- **晚上：** 通关考核。
- **通关标准：** 不看资料，画出（或用文字描述）五种 workflow 模式的结构，每种举一个 Web3 场景的例子。

### Day 2｜LLM API 基础
- **上午：** Claude 文档：https://platform.claude.com/docs/en/overview （Messages API、上下文窗口、计费部分）
- **下午：** 用 Python SDK 写多轮对话程序；做"不传历史，看模型失忆"的实验。
- **通关标准：** 能解释"模型无状态"，并用实验结果证明。

### Day 3｜JSON Schema + 工具调用（全路线最重要的一天）
- **上午：**
  - JSON Schema：https://json-schema.org/learn/getting-started-step-by-step （重点掌握 `type`、`properties`、`required`、`enum`、`description`）
  - Tool use 文档：https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview ，包括文档目录里的工具调用 agent 搭建教程、工具定义、工具调用处理、并行工具调用等章节
- **下午（自己写）：** 双工具程序（如"计算"和"读本地文件"），打印每一轮请求和响应的完整 JSON。
- **通关标准：** 对着打印出来的 JSON，逐字段解释一次工具调用往返；说出 `stop_reason` 的各种取值，以及每种值对循环意味着什么。

### Day 4｜工程补课 + API 进阶
- **上午：**
  - Claude 文档侧边栏中的 structured outputs、streaming、prompt caching 三部分
  - Pydantic：https://docs.pydantic.dev/latest/
  - asyncio：https://docs.python.org/3/library/asyncio.html
- **下午：**
  - 让模型稳定输出符合 Pydantic schema 的 JSON
  - 把 D2 的程序改成流式输出
  - 写一个并发请求三个 API 的小程序，对比串行和并发的耗时
  - Docker：https://docs.docker.com/get-started/ ，把 D3 的程序装进容器运行
- **晚上：** 浏览 Claude Cookbooks：https://github.com/anthropics/claude-cookbooks 的 `tool_use/` 目录
- **通关标准：** Pydantic 模型导出的 schema 能直接当工具定义使用；程序能在容器里正常运行。

### Day 5｜工具设计、上下文工程、prompt engineering
- **上午：**
  - 《Writing effective tools for agents》：https://www.anthropic.com/engineering/writing-tools-for-agents
  - 《Effective context engineering for AI agents》：https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
  - Prompt engineering：https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- **下午（加练）：** 用 OpenAI API 把 D3 的程序再实现一遍（文档：https://platform.openai.com/docs/guides/function-calling ），对比两家协议的差异：消息结构、工具结果怎么回传、并行调用怎么表示。
- **通关标准：** 写出 5 条工具设计原则，并据此重构 D3 的工具；列出两家 tool use 协议的 3 处差异。

### Day 6｜mini-swe-agent
- **上午：** 仓库：https://github.com/SWE-agent/mini-swe-agent ，先运行，再找到核心循环文件逐行阅读。
- **下午：** 给它 3 个不同难度的任务，观察日志，找出它在哪里犯错、又是怎么恢复的。
- **重点：** 循环什么时候停、模型输出怎么解析成命令、报错怎么喂回给模型。
- **通关标准：** 不看代码，复述它的完整循环。

### Day 7｜自己的 agent + 第一周复盘
- **上午（自己写）：** 不用框架，写约 50 行的 agent，工具为 bash 或文件读写，任务是"找出目录里所有 TODO 注释并汇总成 markdown"。必须包含最大步数限制和错误回传。
- **下午（加练）：** 加上流式输出，实时显示模型的思考和工具调用。
- **晚上：** 对比你的代码和 mini-swe-agent，列出 3 处差异。
- **通关标准：** agent 能稳定完成 TODO 汇总任务。

---

# 第 2 周：读高手项目

### Day 8｜smolagents
- **上午：** 仓库：https://github.com/huggingface/smolagents ，重点看 `CodeAgent` 和 `ToolCallingAgent` 的区别。
- **下午：** 用两种 agent 分别完成同一个任务，对比步数和成功率。
- **通关标准：** 写一段话："它解决了什么问题 + 最值得借鉴的一个设计"；说清楚"用代码当动作"的好处和风险。

### Day 9｜SWE-agent
- **上午：**
  - 论文：https://arxiv.org/abs/2405.15793 （重点读 ACI 设计章节）
  - 仓库：https://github.com/SWE-agent/SWE-agent （工具定义部分）
- **下午（加练）：** 用 mini-swe-agent 跑几个 SWE-bench Lite 任务，读完整轨迹，找出它走弯路的地方。
- **通关标准：** 解释文件查看器限制行数、编辑命令自带 lint 这两个设计，分别是在防止模型犯什么错。

### Day 10｜AST + Aider
- **上午：**
  - Python `ast`：https://docs.python.org/3/library/ast.html
  - tree-sitter：https://tree-sitter.github.io/tree-sitter/
  - Repo map 原理：https://aider.chat/2023/10/22/repomap.html
  - 仓库：https://github.com/Aider-AI/aider
- **下午（加练）：** 用 `ast` 实现简化版 repo map：抽取一个项目中所有函数和类的签名，压缩后放进你的 agent 的上下文。
- **通关标准：** 你的 repo map 能在 2000 token 以内概括一个中型 Python 项目；解释 Aider 为什么用 search/replace 块编辑文件。

### Day 11｜OpenHands
- **上午：** OpenHands 现在拆成了多个仓库，主仓库以 TypeScript 前端和控制中心为主，构建 agent 的模块化 Python SDK 单独放在 software-agent-sdk 里。所以直接读 SDK：https://github.com/OpenHands/software-agent-sdk
- **下午：** 画出它的架构图：事件流（action / observation）、决策层、执行环境、沙箱。
- **晚上：** 选读《Scaling Managed Agents: Decoupling the brain from the hands》：https://www.anthropic.com/engineering/managed-agents ，和 OpenHands 的分层思路对照。
- **通关标准：** 说清楚"决策"和"执行"分离对安全和回放有什么好处。

### Day 12｜LangGraph
- **上午：**
  - 仓库：https://github.com/langchain-ai/langgraph
  - LangChain Academy：https://academy.langchain.com （LangGraph 入门课前两个模块）
- **下午：** 用 LangGraph 重写 D7 的 agent，加一个"执行危险命令前暂停，等人确认"的节点。
- **通关标准：** 说出什么场景下应该用显式状态机，什么场景下用一个大循环就够了。

### Day 13｜OpenAI Agents SDK + 评估
- **上午：**
  - 仓库：https://github.com/openai/openai-agents-python （handoffs、guardrails、tracing）
  - 《Demystifying evals for AI agents》：https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- **下午：** 给 D7 的 agent 准备 5 个测试任务，写批量运行脚本，统计成功率，作为基线。
- **通关标准：** 有一个可重复运行的评估脚本，并记录下基线成功率。

### Day 14｜升级 agent + 第二周复盘
- **上午：** 把这周学到的设计加到自己的 agent 上：工具输出截断（SWE-agent）、repo map（Aider）、事件日志（OpenHands）。
- **下午（加练）：** 写对比笔记：mini-swe-agent、SWE-agent、Aider、OpenHands 在工具设计和上下文管理上的取舍。
- **晚上：** 缓冲时间。
- **通关标准：** 升级后的 agent 在 5 个测试任务上的成功率高于 D13 的基线。

---

# 第 3 周：记忆、MCP、Web3、毕业项目

### Day 15｜Embedding 与记忆
- **上午：**
  - MemGPT 论文：https://arxiv.org/abs/2310.08560
  - 仓库：https://github.com/letta-ai/letta （看记忆分层的实现）
- **下午（自己写）：**
  - 最小的"文本存入 → 语义检索"程序，测试不同 chunking 方式的效果
  - 加练：给你的 agent 实现 MemGPT 式自编辑记忆，让它通过工具自己决定什么信息存入长期记忆
- **通关标准：** 说清楚 core memory 和 archival memory 各解决什么问题；你的 agent 能在新会话中召回上一次存入的信息。

### Day 16｜MCP + TypeScript 工程准备
- **上午：**
  - MCP 规范和教程：https://modelcontextprotocol.io
  - 《Code execution with MCP》：https://www.anthropic.com/engineering/code-execution-with-mcp
- **下午：** 写一个 MCP server，提供"查询地址 ETH 余额"工具，接入你的 agent。
- **晚上：**
  - Bun 文档：https://bun.sh/docs （`bun install`、`bun run`、workspace）
  - clone ElizaOS 并成功安装依赖，确保 D17 可以直接读代码。
- **通关标准：** 你的 agent 能通过 MCP 调用余额查询工具；ElizaOS 在本地能运行起来。

### Day 17｜ElizaOS
- **上午：** 仓库：https://github.com/elizaOS/eliza 。运行时核心在 packages/core，包括 agent 循环、插件模型、消息/记忆/状态原语，从这里入手。
- **下午：** 插件可以注册 actions、providers、evaluators、services 等。挑一个官方插件，搞清楚这几类概念分别在做什么，并画出一条消息从进入到回复的完整路径。
- **通关标准：** 说清楚 actions、providers、evaluators 的区别，并各举一个链上场景的例子。

### Day 18｜链上工具层 + 安全
- **上午：**
  - GOAT SDK：https://github.com/goat-sdk/goat
  - Coinbase AgentKit：https://github.com/coinbase/agentkit
  - viem：https://viem.sh （交易构造、`simulateContract`）
- **下午：** 写一份安全设计文档，作为毕业项目的规范：私钥隔离、交易模拟、金额上限、地址白名单、人工确认、session key、prompt injection 防护（例如恶意代币名称诱导转账）。
- **通关标准：** 说清楚 GOAT 和 AgentKit 是怎么让私钥远离模型上下文的；安全文档覆盖以上全部 7 项。

### Day 19｜毕业项目（一）：只读版
自己写一个链上分析 agent：
- 工具通过 MCP 提供（复用 D16）
- 包含"查询余额 / 交易记录"和"模拟交易"两类工具
- 包含最大步数、工具输出截断、事件日志、D15 的长期记忆
- 用 D13 的方法写 5 个测试任务
- **通关标准：** 只读版通过全部 5 个测试任务。

### Day 20｜毕业项目（二）：testnet 写操作
- 加入 testnet 转账功能，严格按照 D18 的安全文档实现：交易模拟、金额上限、白名单、人工确认，最后加上 session key。
- 新增 3 个安全测试任务，例如"用户诱导转账到白名单外的地址"，验证 agent 会拒绝。
- **通关标准：** 8 个测试任务全部通过，其中 3 个安全测试 agent 都正确拒绝了。

### Day 21｜收尾
- **上午：** 缓冲时间。
- **下午：**
  - 加练：把毕业项目的核心能力包装成一个 ElizaOS 插件
  - 写 README：架构图、设计取舍、每个设计借鉴自哪个项目
  - 开源到 GitHub，写一个技术 thread 讲清设计思路
- **晚上：**
  - 读《Effective harnesses for long-running agents》：https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
  - 总复盘：重新回答 Day 1 的问题"workflow 和 agent 怎么选"，对比三周前的答案。
- **通关标准：** 项目已开源，README 完整，你能在 5 分钟内向别人讲清楚整个架构。

---

计划到这里就全部排好了。下一步从 Day 0 的自检开始，做完后把五项结果发给我。

---

# you asked

给我相关的先详细学习链接呀，最好全面一点

---

# claude response

下面是一份完整的学习链接库，按模块整理，每个链接都标注了"看什么"和"对应哪一天"。中文资源能帮你提速的地方，我都一并列了出来。

使用前的两点说明：
- 英文官方文档是一手资料，最准确；中文资源适合用来快速入门或者辅助理解，两者可以对照着看。
- 大部分链接是长期稳定的官方地址。开源项目的文档偶尔会搬家，如果某个链接打不开，搜索资源名称就能找到新地址。

---

## 模块 A：工程基础（Day 0）

**Shell / Bash**
- *The Missing Semester*（MIT）：https://missing.csail.mit.edu
  中文版：https://missing-semester-cn.github.io
  看什么：第 1 讲（Shell）、第 2 讲（Shell 工具与脚本）、第 4 讲（数据整理）。
- 网道 Bash 教程（中文）：https://wangdoc.com/bash/
  看什么：当作手册查阅，重点看变量、管道、重定向、退出码。
- explainshell：https://explainshell.com
  用法：把看不懂的命令贴进去，它会逐段解释每个参数。读 mini-swe-agent 日志时很好用。

**Git**
- *Pro Git* 中文版：https://git-scm.com/book/zh/v2
  看什么：第 2 章（Git 基础）、第 3 章（分支）、第 7.10 节（使用 Git 调试，包括 blame）。
- Learn Git Branching（交互式练习）：https://learngitbranching.js.org/?locale=zh_CN
  用法：用可视化的方式练习分支和提交历史，1–2 小时就能把概念打通。
- *The Missing Semester* 第 6 讲（版本控制）：讲清楚 Git 的数据模型（快照、提交、引用），理解了这一层，命令就不用死记了。

**Python**
- 官方教程：https://docs.python.org/zh-cn/3/tutorial/
  看什么：第 9 章（类）。重点复习 dataclass 和类型注解。
- 类型注解：https://docs.python.org/zh-cn/3/library/typing.html
  看什么：`Optional`、`Literal`、`TypedDict`。后面读框架源码时会频繁遇到。
- uv（现代 Python 包管理器）：https://docs.astral.sh/uv/
  看什么：快速入门，学会 `uv venv`、`uv pip install`、`uv run`。clone 开源项目后配环境会快很多。

**TypeScript**
- 官方 Handbook：https://www.typescriptlang.org/docs/handbook/
  看什么：Everyday Types、Narrowing、Generics、Modules。
- 网道 TypeScript 教程（中文）：https://wangdoc.com/typescript/
- TypeScript 入门教程（中文）：https://ts.xcatliu.com

**JSON 与 JSON Schema**
- 入门教程：https://json-schema.org/learn/getting-started-step-by-step
- *Understanding JSON Schema*：https://json-schema.org/understanding-json-schema
  看什么：Type-specific keywords、Object 和 Array 两节。工具定义里会用到的全在这里。

---

## 模块 B：Agent 概念与全景（Day 1，之后反复回看）

- 《Building Effective Agents》：https://www.anthropic.com/engineering/building-effective-agents
  看什么：全文精读，这是整条路线的词汇表。
- ReAct 论文：https://arxiv.org/abs/2210.03629
  看什么：第 1–3 节和图 1、图 2，理解 Thought → Action → Observation 循环的由来。
- Lilian Weng《LLM Powered Autonomous Agents》：https://lilianweng.github.io/posts/2023-06-23-agent/
  看什么：经典综述，把 agent 拆成规划、记忆、工具三部分来讲。虽然写于 2023 年，框架性的理解至今仍然适用。
- Chip Huyen《Agents》：https://huyenchip.com/2025/01/07/agents.html
  看什么：工具选择、规划失败模式、评估方法。比 Lilian Weng 那篇更偏工程实践。
- Barry Zhang 演讲《How We Build Effective Agents》：https://ai.engineer/talks/effective-ai-agents
  看什么：15 分钟，讲什么时候不该做 agent，以及怎么"站在 agent 的视角"去调试。
- Hugging Face Agents Course：https://huggingface.co/learn/agents-course/unit0/introduction
  这门课免费，从 agent 基础概念讲到 smolagents、LlamaIndex、LangGraph 等框架的实践，还有可观测性和评估的加餐单元；课程团队里有中文译者，页面可以切换中文。
  看什么：Unit 1 配合 Day 1–3 阅读；Unit 2 的 smolagents 部分配合 Day 8；LangGraph 部分配合 Day 12；Bonus Unit 2（可观测性与评估）配合 Day 13。
- Anthropic 工程博客总目录：https://www.anthropic.com/engineering
  用法：本路线引用的所有 Anthropic 工程文章都在这里，三周结束后也值得持续关注。

---

## 模块 C：LLM API 与工具调用（Day 2–5）

**Claude 官方文档**
- 总览：https://platform.claude.com/docs/en/overview
  看什么：Messages API、上下文窗口、模型与定价。
- Tool use：https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview
  看什么：全部章节，包括工具调用 agent 的搭建教程、并行工具调用、strict 模式。
- Prompt engineering：https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
  看什么：清晰直接的指令、使用示例、使用 XML 标签、system prompt 的角色设定。
- structured outputs、streaming、prompt caching：都在上面文档的侧边栏里（Day 4）。

**Anthropic 官方课程**
- Anthropic Courses：https://github.com/anthropics/courses
  看什么：Prompt engineering interactive tutorial（交互式 notebook，配合 Day 5）；Tool use 课程（配合 Day 3，比文档更循序渐进）。
- Claude Cookbooks：https://github.com/anthropics/claude-cookbooks
  看什么：`tool_use/` 目录（Day 3–4）；`patterns/agents/` 目录，这里有《Building Effective Agents》里五种模式的最小实现，Day 1 读完文章后可以对照着看代码。

**OpenAI 文档（Day 5 对比用）**
- Function calling：https://platform.openai.com/docs/guides/function-calling
- Structured outputs：https://platform.openai.com/docs/guides/structured-outputs

**Prompt 工程中文资料**
- Prompt Engineering Guide 中文版：https://www.promptingguide.ai/zh
  看什么：技术部分的 Few-shot、Chain-of-Thought、ReAct 三节。

---

## 模块 D：Python 异步、Pydantic、Docker（Day 4）

- asyncio 官方文档：https://docs.python.org/zh-cn/3/library/asyncio.html
  看什么：协程与任务、`asyncio.gather`。
- Real Python《Async IO in Python》：https://realpython.com/async-io-python/
  看什么：全文。比官方文档更好懂，讲清楚了协程、事件循环、并发与并行的区别。
- Pydantic：https://docs.pydantic.dev/latest/
  看什么：Models、Fields、JSON Schema 三节。重点是 `model_json_schema()` 方法。
- Docker 官方入门：https://docs.docker.com/get-started/
- 《Docker — 从入门到实践》（中文）：https://yeasy.gitbook.io/docker_practice
  看什么：基本概念、使用镜像、操作容器、Dockerfile 指令详解。

---

## 模块 E：工具设计、上下文工程、评估（Day 5、Day 13）

- 《Writing effective tools for agents》：https://www.anthropic.com/engineering/writing-tools-for-agents
- 《Effective context engineering for AI agents》：https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- 《Demystifying evals for AI agents》：https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Hamel Husain《Your AI Product Needs Evals》：https://hamel.dev/blog/posts/evals/
  看什么：从业者视角讲怎么搭评估体系，对 Day 13 的评估脚本非常有帮助。
- SWE-bench 官网：https://www.swebench.com
  看什么：了解 benchmark 是怎么构造的，以及 Lite 子集是什么（Day 9 加练会用到）。

---

## 模块 F：高手项目源码与文档（Day 6–12）

| 天 | 项目 | 仓库 | 文档 / 补充资料 |
|---|---|---|---|
| D6 | mini-swe-agent | https://github.com/SWE-agent/mini-swe-agent | 仓库 README 里有文档链接 |
| D8 | smolagents | https://github.com/huggingface/smolagents | https://huggingface.co/docs/smolagents |
| D9 | SWE-agent | https://github.com/SWE-agent/SWE-agent | 论文：https://arxiv.org/abs/2405.15793 ；文档：https://swe-agent.com |
| D10 | Aider | https://github.com/Aider-AI/aider | Repo map：https://aider.chat/2023/10/22/repomap.html ；文档：https://aider.chat/docs/ |
| D11 | OpenHands | https://github.com/OpenHands/software-agent-sdk | 文档：https://docs.openhands.dev ；配套阅读：https://www.anthropic.com/engineering/managed-agents |
| D12 | LangGraph | https://github.com/langchain-ai/langgraph | 课程：https://academy.langchain.com ；文档链接见仓库 README |
| D13 | OpenAI Agents SDK | https://github.com/openai/openai-agents-python | 文档：https://openai.github.io/openai-agents-python/ |

**读源码的辅助工具**
- DeepWiki：https://deepwiki.com
  用法：把 github.com 换成 deepwiki.com 就能看到 AI 生成的仓库结构说明。适合第一次打开陌生项目时先建立全局印象，但细节要以源码为准。

---

## 模块 G：AST 与代码解析（Day 10）

- Python `ast` 模块：https://docs.python.org/zh-cn/3/library/ast.html
  看什么：`ast.parse`、`ast.walk`、`FunctionDef` 和 `ClassDef` 节点。
- Green Tree Snakes（AST 入门指南）：https://greentreesnakes.readthedocs.io
  看什么：比官方文档更友好，有大量例子。
- tree-sitter：https://tree-sitter.github.io/tree-sitter/
  看什么：Using Parsers 一节，理解"语法树"和"查询"的概念。
- py-tree-sitter：https://github.com/tree-sitter/py-tree-sitter
  看什么：README 里的例子。如果你想让 repo map 支持 Python 以外的语言，就要用它。

---

## 模块 H：Embedding、RAG 与记忆（Day 15）

- MemGPT 论文：https://arxiv.org/abs/2310.08560
- Letta：https://github.com/letta-ai/letta ；文档：https://docs.letta.com
- OpenAI Embeddings 指南：https://platform.openai.com/docs/guides/embeddings
  看什么：embedding 是什么、怎么计算相似度。概念适用于所有厂商。
- Sentence Transformers：https://sbert.net
  用法：可以在本地免费跑 embedding 模型，做实验不用花 API 费用。
- Pinecone Learn：https://www.pinecone.io/learn/
  看什么：搜索 chunking strategies 相关文章，讲不同切块方式对检索效果的影响。
- Claude Cookbooks 的 RAG 部分：https://github.com/anthropics/claude-cookbooks （`capabilities/` 目录下的检索增强相关 notebook）

---

## 模块 I：MCP（Day 16）

- 官网（规范 + 教程）：https://modelcontextprotocol.io
  看什么：入门介绍、核心架构、"构建 server"教程。
- Python SDK：https://github.com/modelcontextprotocol/python-sdk
- TypeScript SDK：https://github.com/modelcontextprotocol/typescript-sdk
- 官方 server 示例集：https://github.com/modelcontextprotocol/servers
  用法：挑一两个简单的 server（比如 filesystem）读源码，看别人怎么写工具描述。
- 《Code execution with MCP》：https://www.anthropic.com/engineering/code-execution-with-mcp
- DeepLearning.AI 短课《MCP: Build Rich-Context AI Apps with Anthropic》：https://www.deeplearning.ai/short-courses/mcp-build-rich-context-ai-apps-with-anthropic/
  看什么：视频课，手把手搭建 MCP server 和 client，可以配合官网教程一起学。

---

## 模块 J：TypeScript 工程化（Day 16 晚上）

- Bun 文档：https://bun.sh/docs
  看什么：安装、`bun install`、`bun run`、Workspaces。
- pnpm Workspaces：https://pnpm.io/workspaces
  看什么：理解 monorepo 里各个包之间是怎么互相引用的，看 ElizaOS 的 `package.json` 时会用到。

---

## 模块 K：Web3 Agent（Day 17–18）

- ElizaOS：https://github.com/elizaOS/eliza
  看什么：`packages/core`；文档链接在 README 里，重点看插件开发部分。
- ElizaOS 插件注册表：https://github.com/elizaOS-plugins/registry
  用法：挑一个链上相关的插件（比如 EVM 插件）作为 Day 17 下午的阅读对象。
- GOAT SDK：https://github.com/goat-sdk/goat
  看什么：wallet 抽象层和插件结构，以及怎么把链上操作转成工具定义。
- Coinbase AgentKit：https://github.com/coinbase/agentkit
  看什么：action providers 和 wallet providers 的设计。
- viem 文档：https://viem.sh
  看什么：Clients、`simulateContract`（https://viem.sh/docs/contract/simulateContract）、`sendTransaction`。
- ERC-4337（账户抽象）：https://eips.ethereum.org/EIPS/eip-4337
  看什么：理解 UserOperation 和 smart account，这是 session key 方案的基础。
- Tenderly 交易模拟：https://docs.tenderly.co/simulations
  看什么：除了 `eth_call` 以外，更完整的模拟方案（可以看到状态变化和事件）。

---

## 模块 L：Agent 安全（Day 18–20）

- OWASP Top 10 for LLM Applications：https://genai.owasp.org/llm-top-10/
  看什么：Prompt Injection、Excessive Agency（权限过大）、Sensitive Information Disclosure 三项，跟链上 agent 直接相关。
- Simon Willison 的 prompt injection 系列：https://simonwillison.net/series/prompt-injection/
  看什么：这是讲 prompt injection 最清楚的系列文章，先读最早的几篇建立概念。
- Simon Willison《The lethal trifecta》：https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
  看什么：当 agent 同时具备"能接触私密数据""会读取不可信内容""能向外部发送信息"这三个条件时，风险会急剧上升。用这个框架来审视你的毕业项目：链上 agent 往往三条全占。

---

## 模块 M：收尾阅读（Day 21）

- 《Effective harnesses for long-running agents》：https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- 《Building a C compiler with a team of parallel Claudes》：https://www.anthropic.com/engineering/building-c-compiler
  看什么：多个 agent 并行协作完成大型工程的实战记录，可以作为三周学习之后的延伸方向。

---

## 怎么用这份链接库

每天开始时，先打开对应模块里标了当天日期的链接；中文资源用来快速入门，英文官方文档用来确认细节。遇到链接里没覆盖到的问题，带着具体问题来问我，比漫无目的地搜索效率高得多。

现在可以从 Day 0 开始：先看 *The Missing Semester* 中文版的第 1 讲，然后做自检。

---

# you asked

还要补充一个FAStAPI

---

# claude response

好的，FastAPI 很值得加进来。先说为什么，再说怎么安排。

## 为什么 agent 开发需要 FastAPI

到目前为止，你写的 agent 都是在终端里运行的脚本。但真实的 agent 几乎都是以**服务**的形式存在的：前端、Telegram 机器人或者其他程序，通过 HTTP 来调用它。FastAPI 是 Python 里做这件事最常用的框架，而且跟这条路线的契合度非常高：

1. **它就建立在你 Day 4 学的两样东西上。** FastAPI 用 Pydantic 校验请求和响应，用 async/await 处理并发。你会发现"定义一个 API 的请求体"和"定义一个工具的参数"写法几乎一样，都是 Pydantic 模型导出 JSON Schema。学 FastAPI 本身就是在巩固 Day 4。
2. **agent 的输出需要流式传输。** agent 一次运行可能要几十秒，用户不能干等。FastAPI 可以用 SSE（Server-Sent Events）把模型的思考过程和工具调用一条条实时推给前端。
3. **人工确认需要一个接口。** Day 12 的"危险操作前暂停"和 Day 20 的"转账前人工确认"，在真实系统里就是 agent 暂停后，等用户调用一个"批准 / 拒绝"接口再继续。
4. **MCP 的 Python SDK 风格跟它一脉相承。** MCP 官方 Python SDK 里的 FastMCP 用的是装饰器风格来定义工具，熟悉 FastAPI 之后再看会非常顺手。

---

## 插入位置

FastAPI 不单独占一天，而是拆成 4 段，嵌进已有的天数里，每次都跟当天的内容互相强化：

| 天 | 新增内容 | 时长 | 跟当天内容的关系 |
|---|---|---|---|
| **D4 晚上** | FastAPI 基础：第一步、路径参数、查询参数、请求体、响应模型 | 约 2 小时 | 直接复用当天刚学的 Pydantic 和 async。原定 D4 晚上的 Cookbook 浏览挪到 D5 晚上 |
| **D7 晚上** | 把自己的 agent 包装成服务：`POST /run` 接口 + SSE 流式输出 | 约 2–3 小时 | 当天下午刚做完流式输出，晚上把它接到 HTTP 上 |
| **D12 下午** | 人工确认改成 HTTP 接口：agent 暂停后，通过 `POST /approve/{run_id}` 继续 | 并入原任务 | LangGraph 的 checkpoint 正好解决"暂停后怎么恢复"的问题 |
| **D19–D20** | 毕业项目的后端用 FastAPI：流式对话接口、交易审批接口、依赖注入做 API key 鉴权、用 TestClient 写接口测试 | 并入原任务 | 让毕业项目从"脚本"变成"可部署的服务" |

D4 本来就很满，加上 FastAPI 之后会更紧。如果当天没做完，FastAPI 基础可以挪到 D5 下午，排在 OpenAI 对比加练之前。

**各段的通关标准：**
- **D4**：写一个接口，接收一个 Pydantic 模型作为请求体，并说出 FastAPI 自动生成的 `/docs` 页面里的 schema，跟你 D3 写的工具定义有什么异同。
- **D7**：用 `curl` 调用你的 agent 服务，能在终端里实时看到工具调用一条条流出来。
- **D12**：agent 在执行危险命令前暂停；调用审批接口后，它能从断点继续执行，而不是从头开始。
- **D19–D20**：毕业项目的所有接口都有 TestClient 测试；没有 API key 的请求会被拒绝。

---

## 模块 N：FastAPI 学习链接

**官方文档（有完整中文版）**
- 官网：https://fastapi.tiangolo.com
  中文版：https://fastapi.tiangolo.com/zh/
- 教程 - 用户指南：https://fastapi.tiangolo.com/zh/tutorial/
  D4 看：第一步、路径参数、查询参数、请求体、响应模型。
  D19 看：依赖项（Dependencies）、安全性（Security）、后台任务（Background Tasks）、测试（Testing）。
- 并发与 async/await：https://fastapi.tiangolo.com/zh/async/
  看什么：这一篇非常值得在 D4 读。作者用"汉堡店排队"的比喻讲清楚了并发和并行的区别，以及什么时候该用 `async def`，是我见过最好懂的异步入门之一，可以和 Real Python 那篇对照着看。
- 自定义响应（StreamingResponse）：https://fastapi.tiangolo.com/advanced/custom-response/
  D7 看：流式响应的基本用法。

**流式输出（D7）**
- MDN：Server-Sent Events（中文）：https://developer.mozilla.org/zh-CN/docs/Web/API/Server-sent_events
  看什么：SSE 的协议格式（`data:` 行、空行分隔事件），以及它和 WebSocket 的区别。理解了格式，你就能看懂各家 LLM API 的流式响应，因为它们用的也是 SSE。
- sse-starlette：https://github.com/sysid/sse-starlette
  看什么：README 里的例子。它帮你处理 SSE 的格式细节和断开连接等边界情况，比手写 StreamingResponse 省心。

**运行与部署**
- Uvicorn（运行 FastAPI 的服务器）：https://www.uvicorn.org
  看什么：快速入门、`--reload` 参数。
- FastAPI 部署文档：https://fastapi.tiangolo.com/zh/deployment/
  D21 看：容器中的 FastAPI（Docker）一节，把毕业项目打包成镜像。

**参考项目**
- FastAPI 官方全栈模板：https://github.com/fastapi/full-stack-fastapi-template
  看什么：只看 `backend/` 目录的结构：路由怎么拆分、配置怎么管理、测试怎么组织。毕业项目的后端可以参考这个结构，但不用照搬全部功能。

---

## 更新后的总览

- **Day 0**：前置自检 + 工程工具
- **D1–D7**：LLM API 地基 + 第一个 agent（新增：D4 FastAPI 基础，D7 agent 服务化）
- **D8–D14**：读高手项目（新增：D12 人工确认接口）
- **D15–D21**：记忆、MCP、Web3、毕业项目（新增：D19–D20 FastAPI 后端）

FastAPI 已经整合进计划里了。D4 晚上读"并发与 async/await"那一篇时，可以把你对"汉堡店"比喻的理解讲给我听，我来检查你是否真的分清了并发和并行。

---

# you asked

是不是还少了一个Lanchain

---

# claude response

是的，LangChain 确实值得补上。之前没有单独列出来，是因为路线里已经有 LangGraph（同一个团队出品），而且整条路线的思路是"先徒手写，再看框架"。但 LangChain 在业界、黑客松和各种开源项目里用得太广了，不懂它，你读别人的项目时会经常卡住。所以应该补。

不过补之前，有一件很重要的事要先提醒你。

## 先避坑：LangChain v1 和旧版差别很大

LangChain v1 大幅精简了 `langchain` 包的命名空间，只保留构建 agent 的核心组件；官方现在推荐用 `create_agent` 来构建 agent，而中间件（middleware）是它最核心的特性。旧的 chains、retrievers、hub 等功能被移到了一个叫 `langchain-classic` 的独立包里。

这对你的直接影响是：**网上大量教程已经过时了**，尤其是 2023–2024 年的中文博客。如果你看到教程里在用 `LLMChain`、`AgentExecutor`、`initialize_agent` 这类写法，那就是旧版，直接跳过，以官方文档为准。

另外有一个对 AI 辅助学习特别有用的技巧：LangChain 文档提供了完整的索引文件 https://docs.langchain.com/llms.txt，还支持通过 MCP 把文档接入 Claude、VSCode 等工具来实时查询。问 AI 关于 LangChain 的问题时，先把文档接进去，就能避免 AI 按旧版 API 回答你。

---

## 为什么放在 D12，以及跟 LangGraph 是什么关系

先理解两者的分工：
- **LangChain v1** 是高层接口：用 `create_agent` 几行代码就能得到一个能调用工具的 agent，通过中间件定制行为。
- **LangGraph** 是底层运行时：显式的状态图、checkpoint、持久化。
- 理解这一层关系最好的方式，是**同一个功能在两个层次各实现一遍**。

最好的例子就是人工确认：LangChain v1 内置了 `HumanInTheLoopMiddleware`，可以要求敏感工具调用先经过审批；同样内置的还有对话过长时自动压缩历史的 `SummarizationMiddleware`、以及在发送给模型前脱敏的 `PIIMiddleware`。D12 你本来就要用 LangGraph 手写人工确认节点，两相对照，你就能看清楚高层框架到底替你隐藏了什么。

还有一点：这三个内置中间件做的事，你在前面已经徒手做过类似的了（D7 的步数限制、D14 的输出截断）。所以你读中间件源码时，会有"原来它是这样做的"的感觉，而不是在背 API。这正是"先徒手写，再看框架"的价值。

---

## 插入位置

| 天 | 新增内容 | 说明 |
|---|---|---|
| **D12 上午** | LangChain v1：`create_agent`、`@tool`、`init_chat_model`、中间件机制 | 原定的 LangGraph 阅读挪到 D12 下午 |
| **D12 下午** | LangGraph（原内容） | 不变 |
| **D12 晚上** | 用 `HumanInTheLoopMiddleware` 实现人工确认，跟下午 LangGraph 手写的版本对比；FastAPI 审批接口照原计划做 | D12 会变成全路线最满的一天，D14 晚上的缓冲可以兜底 |
| **D13 加练** | 用 LangSmith 给 agent 加 tracing，跟 OpenAI Agents SDK 的 tracing 对比 | 补强评估和可观测性 |
| **D14 上午加练** | 写一个自定义中间件，把你 D7 徒手写的"最大步数限制"或 D14 的"输出截断"移植成 LangChain 中间件 | 检验你是否真正理解了中间件的钩子机制 |
| **D15 下午加练** | 用 LangChain 的 embeddings 和 vector store 接口重写你的检索程序，对比和徒手版本的差异 | 了解它的集成生态，这是 LangChain 最大的实际优势 |

**D12 新的通关标准：**
1. 用 `create_agent` 重写 D7 的 agent，说出框架替你隐藏了哪 3 件你之前手写的事。
2. 讲清楚 LangChain v1 和 LangGraph 的分工：什么时候用 `create_agent` 就够了，什么时候必须下沉到 LangGraph。
3. 对比 `HumanInTheLoopMiddleware` 和你手写的 LangGraph 审批节点，说出各自的优缺点。

---

## 模块 O：LangChain 学习链接

**官方文档（v1，以此为准）**
- 文档首页：https://docs.langchain.com
  说明：LangChain、LangGraph、LangSmith 的文档现在统一在这个站点下，Python 版在 `/oss/python/` 路径下。
- What's new in LangChain v1：https://docs.langchain.com/oss/python/releases/langchain-v1
  D12 上午第一篇必读：`create_agent`、中间件、包结构的变化。页面里还有中间件完整指南的链接，接着读。
- 迁移指南：https://docs.langchain.com/oss/python/migrate/langchain-v1
  看什么：即使你从来没用过旧版也值得读，它对比了新旧写法。以后读到别人基于旧版写的项目时，你能立刻看懂并知道它对应新版的什么。
- 文档索引（给 AI 用）：https://docs.langchain.com/llms.txt

**源码**
- LangChain 仓库：https://github.com/langchain-ai/langchain
  看什么：找到 `create_agent` 和 `AgentMiddleware` 的实现。重点看中间件的钩子是在 agent 循环的哪些位置被调用的，然后跟你自己写的循环对照。

**课程**
- LangChain Academy：https://academy.langchain.com
  看什么：选 LangChain v1 相关的入门课。课程更新比较快，选标注了 v1 或最新发布的课程，避开旧课。

**可观测性**
- LangSmith：https://smith.langchain.com
  看什么：注册后按引导开启 tracing，文档入口在 docs.langchain.com 的顶部导航。D13 用它来观察 agent 每一步的输入和输出。

---

## 更新后的总览

- **Day 0**：前置自检 + 工程工具
- **D1–D7**：LLM API 地基 + 第一个 agent（含 FastAPI 基础和 agent 服务化）
- **D8–D14**：读高手项目（D12 变为 LangChain v1 + LangGraph 双层对比；D13 加入 LangSmith；D14 加入自定义中间件）
- **D15–D21**：记忆、MCP、Web3、毕业项目（D15 加入 LangChain 检索对比）

到 D12 的时候，你已经徒手写过 agent 循环、步数限制、输出截断和人工确认了。那时再来读 LangChain 中间件的源码，你看到的就不是一堆抽象的 API，而是你自己写过的东西被系统化之后的样子。

---

# you asked

是不是还少了HTTP

---

# claude response

对，这一项之前确实是漏了。在前置条件里我写了"HTTP / REST：你应该已经会了"，但这只是假设，没有安排验证和补强。而且 HTTP 在这条路线里的分量，其实比我当时估计的要重。

## 为什么 HTTP 在 agent 开发里这么重要

你做前端时会用 `fetch` 调接口，这只是 HTTP 的一小部分。在 agent 开发里，HTTP 贯穿了整条路线：

1. **LLM API 本身就是 HTTP。** Claude 和 OpenAI 的 SDK 本质上只是对 HTTP 请求的封装。理解了这一点，SDK 报错时你就知道该看状态码、响应头还是响应体。
2. **流式输出是 SSE。** 模型的流式响应、你 D7 做的 agent 服务，用的都是基于 HTTP 的 Server-Sent Events。
3. **稳定性问题全是 HTTP 问题。** agent 会频繁调用 API，一定会遇到 429（限流）、5xx（服务端错误）、超时。成熟的 agent 都有重试、退避和超时处理，这部分在原计划里完全没有覆盖。
4. **MCP 和以太坊用的是同一个协议。** MCP 的消息格式是 JSON-RPC 2.0，而你熟悉的以太坊节点接口（`eth_call`、`eth_getBalance`）也是 JSON-RPC 2.0。D16 写 MCP server 的时候，你会发现它和你调用以太坊节点是同一种通信模式。这个联系是你独有的优势，值得专门花时间打通。

---

## 插入位置

| 天 | 新增内容 | 说明 |
|---|---|---|
| **Day 0** | 自检第 6 项：HTTP（见下方） | 你有前端经验，大概率能快速通过，主要是查漏补缺 |
| **D2 上午** | 先用 `curl` 直接调 Claude API，再用 SDK | 亲眼看到 SDK 只是 HTTP 的封装：请求头、JSON 请求体、响应结构 |
| **D4 下午** | 用 httpx 的异步客户端做并发请求实验 | 原计划的"并发请求三个 API"直接用 httpx 来写 |
| **D14 上午** | 给 agent 加上稳定性处理：超时、429 和 5xx 的指数退避重试 | 和原计划的工具输出截断、事件日志一起做 |
| **D16 上午** | 对比 JSON-RPC 2.0 规范、MCP 的消息格式和以太坊 JSON-RPC | 读 MCP 规范之前先读 JSON-RPC 规范，后面会顺很多 |

**Day 0 自检第 6 项：HTTP**
能做到以下几点就跳过：
- 说出一个 HTTP 请求由哪几部分组成（方法、URL、请求头、请求体），响应由哪几部分组成。
- 说出 200、400、401、403、404、429、500、503 各自的含义，以及哪些错误值得重试、哪些不该重试。
- 用 `curl` 发一个带请求头和 JSON 请求体的 POST 请求，并用 `-v` 参数看到完整的请求和响应过程。

**新增的通关标准：**
- **D2**：用 `curl` 成功调用 Claude API，并能指出请求和响应里每个字段对应 SDK 中的什么。
- **D14**：人为制造一次失败（比如设置极短的超时），你的 agent 能自动重试并最终成功，而不是直接崩溃。
- **D16**：把一条 MCP 工具调用消息和一条 `eth_getBalance` 请求并排放在一起，指出两者结构上的相同点。

---

## 模块 P：HTTP 学习链接

**基础**
- MDN HTTP 文档（中文）：https://developer.mozilla.org/zh-CN/docs/Web/HTTP
  看什么：HTTP 概述、HTTP 消息、HTTP 请求方法、HTTP 状态码、HTTP 标头这几页。这是讲 HTTP 最权威、最清楚的免费资料。
- Everything curl：https://everything.curl.dev
  看什么：Command line basics 和 HTTP with curl 两部分。重点掌握 `-X`、`-H`、`-d`、`-v`、`-N`（关闭缓冲，看流式输出时要用）。

**Python 中的 HTTP**
- httpx：https://www.python-httpx.org
  看什么：快速入门、Async Support、Timeouts。Claude 和 OpenAI 的 Python SDK 底层用的都是 httpx，学会它等于看懂了 SDK 的网络层。
- Tenacity（重试库）：https://tenacity.readthedocs.io
  D14 看：`retry`、`stop_after_attempt`、`wait_exponential`、`retry_if_exception_type`。

**JSON-RPC（D16）**
- JSON-RPC 2.0 规范：https://www.jsonrpc.org/specification
  看什么：全文只有几页，重点是请求对象、响应对象、错误对象、通知（notification）四个部分。
- 以太坊 JSON-RPC API：https://ethereum.org/zh/developers/docs/apis/json-rpc/
  看什么：你可能已经用过，这次带着"它和 MCP 有什么共同点"的问题重读一遍。
- MCP 规范中的 Transports 章节：在 https://modelcontextprotocol.io 的规范部分里
  看什么：stdio 和 Streamable HTTP 两种传输方式，理解同一套 JSON-RPC 消息是怎么跑在不同传输层上的。

**API 稳定性**
- Claude API 文档中的 Errors 和 Rate limits 页面：在 https://platform.claude.com/docs/en/overview 的 API 参考部分
  看什么：各种错误码的含义，限流是按什么计算的，响应头里哪些字段告诉你还剩多少额度。

---

## 关于"还少了什么"

你一路追问下来，补上了 FastAPI、LangChain、HTTP，这三项确实都该补。不过计划越来越满，我想把边界说清楚，免得你担心还有遗漏。下面这些是**我有意没有放进来的**，原因各不相同：

- **LlamaIndex、CrewAI、AutoGen 等其他框架**：概念和你会学的框架高度重叠。学完 LangChain、LangGraph、smolagents、OpenAI Agents SDK 之后，你看这些框架只需要半天就能上手，没必要在 3 周里专门安排。
- **向量数据库的深入使用**（Pinecone、Milvus、pgvector 等）：D15 理解原理就够了，具体用哪个是工程选型问题，等项目需要时再学。
- **模型微调和训练**：属于另一个方向，做 agent 不需要。
- **Kubernetes、云部署**：D21 的 Docker 已经足够让项目跑起来，规模化部署是之后的事。
- **前端界面**：你本身就会，毕业项目需要界面的话直接用你熟悉的技术栈。

判断一项内容要不要加，可以用这个标准：**它是不是读懂高手项目、或者完成毕业项目所必需的？** 如果你之后还觉得缺了什么，用这个标准过一遍，拿不准的话再来问我。

---

# you asked

请全部详细安排会后给我

---

# claude response

下面是整合了全部内容的最终版：22 天（Day 0 到 Day 21），包含 FastAPI、LangChain、HTTP，所有链接都直接放在对应的日期里，按这一份执行即可。

---

# 总则

**每日节奏（6–8 小时）**
- 上午：读。文档、论文、源码，边读边用自己的话记笔记。
- 下午：写。当天的动手任务，核心代码自己写。
- 晚上：考。把笔记和代码发给我，我出题考你或者 review 代码。答不上来的地方，第二天上午优先补。

**通关规则**
每天都有通关标准，达不到就不进入下一天。

**AI 辅助规则**
- 可以让 AI 做：解释代码段、出自检题、review 代码、在大仓库里定位入口文件。
- 必须自己写：D3 工具调用程序、D7 最小 agent、D15 记忆模块、D19–D20 毕业项目。
- 提问方式：先说出你的理解，再让 AI 纠正。
- 读陌生仓库：先用 DeepWiki（https://deepwiki.com ，把 github.com 换成 deepwiki.com）建立全局印象，细节以源码为准。
- 问 LangChain 相关问题：先把 https://docs.langchain.com/llms.txt 提供给 AI，避免它按旧版 API 回答。

**缓冲时间**
D14 晚上、D21 上午。没有欠账就提前推进后面的内容。

**两个重要提醒**
- LangChain 已经升级到 v1，写法和旧版差别很大。看到 `LLMChain`、`AgentExecutor`、`initialize_agent` 的教程就是旧版，直接跳过。
- 开源项目的文档偶尔会搬家，链接打不开时搜索资源名称即可。

---

# Day 0｜前置自检 + 工程工具

**上午：自检。** 能做到就跳过，做不到就下午补：
1. Shell：看懂 `grep -rn "TODO" . | wc -l` 每一部分，知道退出码是什么、怎么查。
2. Git：会用 `git log --oneline`、`git diff`、`git blame`。
3. Python：能写带类型注解的 dataclass，知道 `async def` 和普通函数的区别。
4. TypeScript：看得懂泛型、interface、`async/await`、`import type`。
5. JSON：能手写嵌套对象和数组，知道怎么校验格式。
6. HTTP：说出请求和响应的组成部分；说出 200、400、401、403、404、429、500、503 的含义，以及哪些该重试；用 `curl -v` 发一个带请求头和 JSON 请求体的 POST 请求。

**下午：补课（按自检结果选）。**
- Shell：*The Missing Semester* 中文版 https://missing-semester-cn.github.io （第 1、2、4 讲）；网道 Bash 教程 https://wangdoc.com/bash/ ；explainshell https://explainshell.com
- Git：*Pro Git* 中文版 https://git-scm.com/book/zh/v2 （第 2、3 章，第 7.10 节）；Learn Git Branching https://learngitbranching.js.org/?locale=zh_CN ；*The Missing Semester* 第 6 讲
- Python：官方教程 https://docs.python.org/zh-cn/3/tutorial/ （第 9 章）；typing 模块 https://docs.python.org/zh-cn/3/library/typing.html ；uv https://docs.astral.sh/uv/
- TypeScript：Handbook https://www.typescriptlang.org/docs/handbook/ ；网道 TypeScript 教程 https://wangdoc.com/typescript/
- HTTP：MDN HTTP 文档 https://developer.mozilla.org/zh-CN/docs/Web/HTTP （概述、消息、请求方法、状态码、标头）；Everything curl https://everything.curl.dev （Command line basics、HTTP with curl）

**晚上：** 把六项自检结果发给我。

**通关标准：**
- 用 `git log` 和 `git blame` 在任意开源仓库里找到某个函数最近一次修改的 commit，一句话说清改动原因。
- 用 `curl -v` 请求任意公开 API，逐行解释输出中的请求头和响应头。

---

# 第 1 周：地基 + 第一个 agent

## Day 1｜心智模型

**上午：**
- 《Building Effective Agents》：https://www.anthropic.com/engineering/building-effective-agents （全文精读）
- ReAct 论文：https://arxiv.org/abs/2210.03629 （全文）

**下午：**
- Lilian Weng《LLM Powered Autonomous Agents》：https://lilianweng.github.io/posts/2023-06-23-agent/
- Chip Huyen《Agents》：https://huyenchip.com/2025/01/07/agents.html
- Barry Zhang 演讲：https://ai.engineer/talks/effective-ai-agents
- Hugging Face Agents Course Unit 1：https://huggingface.co/learn/agents-course/unit0/introduction （页面可以切换中文）

**晚上：**
- Claude Cookbooks 的 `patterns/agents/` 目录：https://github.com/anthropics/claude-cookbooks ，对照五种模式的最小实现代码。
- 通关考核。

**通关标准：** 不看资料，画出（或用文字描述）五种 workflow 模式的结构，每种举一个 Web3 场景的例子。

## Day 2｜LLM API 基础

**上午：**
- Claude 文档：https://platform.claude.com/docs/en/overview （Messages API、上下文窗口、计费）
- 先不用 SDK，直接用 `curl` 调用 Claude API，观察请求头、请求体和响应结构。

**下午：**
- 用 Python SDK 写多轮对话程序。
- 做"不传历史，看模型失忆"的实验。

**通关标准：**
- 能解释"模型无状态"，并用实验结果证明。
- 能指出 `curl` 请求和响应里的每个字段，分别对应 SDK 中的什么。

## Day 3｜JSON Schema + 工具调用（全路线最重要的一天）

**上午：**
- JSON Schema 入门：https://json-schema.org/learn/getting-started-step-by-step
- *Understanding JSON Schema*：https://json-schema.org/understanding-json-schema （Type-specific keywords、Object、Array）
- Tool use 文档：https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview （全部章节，包括搭建工具调用 agent 的教程）

**下午（自己写）：**
- 双工具程序（如"计算"和"读本地文件"），打印每一轮请求和响应的完整 JSON。

**晚上：**
- Anthropic Courses 的 Tool use 课程：https://github.com/anthropics/courses ，用来查漏补缺。

**通关标准：**
- 对着 JSON 逐字段解释一次工具调用往返。
- 说出 `stop_reason` 的各种取值，以及每种值对循环意味着什么。

## Day 4｜工程补课 + API 进阶 + FastAPI 基础

**上午：**
- Claude 文档侧边栏中的 structured outputs、streaming、prompt caching
- Pydantic：https://docs.pydantic.dev/latest/ （Models、Fields、JSON Schema）
- asyncio：https://docs.python.org/zh-cn/3/library/asyncio.html
- Real Python《Async IO in Python》：https://realpython.com/async-io-python/
- FastAPI《并发与 async/await》：https://fastapi.tiangolo.com/zh/async/

**下午：**
- 让模型稳定输出符合 Pydantic schema 的 JSON。
- 把 D2 的程序改成流式输出。
- 用 httpx 异步客户端（https://www.python-httpx.org ，看 Async Support）并发请求三个 API，对比串行和并发的耗时。
- Docker：https://docs.docker.com/get-started/ ，或中文的《Docker — 从入门到实践》https://yeasy.gitbook.io/docker_practice 。把 D3 的程序装进容器运行。

**晚上：FastAPI 基础**
- 教程：https://fastapi.tiangolo.com/zh/tutorial/ （第一步、路径参数、查询参数、请求体、响应模型）
- 写一个接收 Pydantic 模型作为请求体的接口，打开自动生成的 `/docs` 页面看看。
- 如果当天做不完，FastAPI 部分挪到 D5 下午。

**通关标准：**
- Pydantic 模型导出的 schema 能直接当工具定义使用。
- 程序能在容器里正常运行。
- 说出 FastAPI `/docs` 页面里的 schema 和 D3 工具定义的异同。
- 用"汉堡店"的比喻讲清楚并发和并行的区别。

## Day 5｜工具设计、上下文工程、prompt engineering

**上午：**
- 《Writing effective tools for agents》：https://www.anthropic.com/engineering/writing-tools-for-agents
- 《Effective context engineering for AI agents》：https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Prompt engineering 文档：https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview
- Anthropic Courses 的 Prompt engineering interactive tutorial：https://github.com/anthropics/courses
- Prompt Engineering Guide 中文版：https://www.promptingguide.ai/zh （Few-shot、CoT、ReAct）

**下午（加练）：**
- 用 OpenAI API 把 D3 的程序再实现一遍：https://platform.openai.com/docs/guides/function-calling
- 对比两家协议：消息结构、工具结果怎么回传、并行调用怎么表示。
- OpenAI structured outputs：https://platform.openai.com/docs/guides/structured-outputs

**晚上：**
- Claude Cookbooks 的 `tool_use/` 目录。

**通关标准：**
- 写出 5 条工具设计原则，并据此重构 D3 的工具。
- 列出两家 tool use 协议的 3 处差异。

## Day 6｜mini-swe-agent

**上午：**
- 仓库：https://github.com/SWE-agent/mini-swe-agent ，先运行，再找到核心循环文件逐行阅读。

**下午：**
- 给它 3 个不同难度的任务，观察日志，找出它在哪里犯错、又是怎么恢复的。看不懂的命令用 explainshell 查。

**重点：** 循环什么时候停、模型输出怎么解析成命令、报错怎么喂回给模型。

**通关标准：** 不看代码，复述它的完整循环。

## Day 7｜自己的 agent + 服务化

**上午（自己写）：**
- 不用框架，写约 50 行的 agent，工具为 bash 或文件读写，任务是"找出目录里所有 TODO 注释并汇总成 markdown"。
- 必须包含最大步数限制、错误回传。

**下午：**
- 加上流式输出，实时显示模型的思考和工具调用。
- 对比你的代码和 mini-swe-agent，列出 3 处差异。

**晚上：agent 服务化**
- MDN Server-Sent Events：https://developer.mozilla.org/zh-CN/docs/Web/API/Server-sent_events
- FastAPI 自定义响应：https://fastapi.tiangolo.com/advanced/custom-response/
- sse-starlette：https://github.com/sysid/sse-starlette
- Uvicorn：https://www.uvicorn.org
- 动手：把 agent 包装成 `POST /run` 接口，用 SSE 流式输出过程。

**通关标准：**
- agent 能稳定完成 TODO 汇总任务。
- 用 `curl -N` 调用你的服务，能在终端里实时看到工具调用一条条流出来。

---

# 第 2 周：读高手项目

## Day 8｜smolagents

**上午：**
- 仓库：https://github.com/huggingface/smolagents
- 文档：https://huggingface.co/docs/smolagents
- 重点看 `CodeAgent` 和 `ToolCallingAgent` 的区别。

**下午：**
- 用两种 agent 分别完成同一个任务，对比步数和成功率。
- Hugging Face Agents Course Unit 2 的 smolagents 部分。

**通关标准：**
- 写一段话："它解决了什么问题 + 最值得借鉴的一个设计"。
- 说清"用代码当动作"的好处和风险。

## Day 9｜SWE-agent

**上午：**
- 论文：https://arxiv.org/abs/2405.15793 （重点读 ACI 设计章节）
- 仓库：https://github.com/SWE-agent/SWE-agent （工具定义部分）
- 文档：https://swe-agent.com

**下午（加练）：**
- 了解 SWE-bench：https://www.swebench.com
- 用 mini-swe-agent 跑几个 SWE-bench Lite 任务，读完整轨迹，找出它走弯路的地方。

**通关标准：** 解释"文件查看器限制行数"和"编辑命令自带 lint"这两个设计，分别在防止模型犯什么错。

## Day 10｜AST + Aider

**上午：**
- Python `ast`：https://docs.python.org/zh-cn/3/library/ast.html
- Green Tree Snakes：https://greentreesnakes.readthedocs.io
- tree-sitter：https://tree-sitter.github.io/tree-sitter/
- py-tree-sitter：https://github.com/tree-sitter/py-tree-sitter
- Repo map 原理：https://aider.chat/2023/10/22/repomap.html
- 仓库：https://github.com/Aider-AI/aider ；文档：https://aider.chat/docs/

**下午（加练）：**
- 用 `ast` 实现简化版 repo map：抽取一个项目中所有函数和类的签名，压缩后放进你的 agent 的上下文。

**通关标准：**
- 你的 repo map 能在 2000 token 以内概括一个中型 Python 项目。
- 解释 Aider 为什么用 search/replace 块编辑文件。

## Day 11｜OpenHands

**上午：**
- OpenHands 现在拆成了多个仓库：主仓库以 TypeScript 前端和控制中心为主，构建 agent 的模块化 Python SDK 单独放在 software-agent-sdk 里。所以直接读 SDK：https://github.com/OpenHands/software-agent-sdk
- 文档：https://docs.openhands.dev

**下午：**
- 画出架构图：事件流（action / observation）、决策层、执行环境、沙箱。

**晚上：**
- 《Scaling Managed Agents: Decoupling the brain from the hands》：https://www.anthropic.com/engineering/managed-agents ，和 OpenHands 的分层思路对照。

**通关标准：** 说清楚"决策"和"执行"分离对安全和回放有什么好处。

## Day 12｜LangChain v1 + LangGraph（全路线最满的一天）

**上午：LangChain v1**
- What's new in LangChain v1：https://docs.langchain.com/oss/python/releases/langchain-v1 ，以及页面里链接的中间件完整指南
- 迁移指南：https://docs.langchain.com/oss/python/migrate/langchain-v1
- 仓库：https://github.com/langchain-ai/langchain ，找到 `create_agent` 和 `AgentMiddleware` 的实现，看中间件的钩子在 agent 循环的哪些位置被调用。
- `create_agent` 是 LangChain 1.0 构建 agent 的标准方式，中间件是它最核心的特性。
- 动手：用 `create_agent` 重写 D7 的 agent。

**下午：LangGraph**
- 仓库：https://github.com/langchain-ai/langgraph
- LangChain Academy：https://academy.langchain.com （选 LangGraph 入门课和 LangChain v1 相关课程，避开旧课）
- Hugging Face Agents Course Unit 2 的 LangGraph 部分
- 动手：用 LangGraph 重写 D7 的 agent，加一个"执行危险命令前暂停，等人确认"的节点。

**晚上：同一功能，两个层次**
- 用 `HumanInTheLoopMiddleware` 再实现一遍人工确认，和下午 LangGraph 的版本对比。LangChain v1 还内置了对话过长时压缩历史的 `SummarizationMiddleware`，以及发送前脱敏的 `PIIMiddleware`，可以顺带看看。
- 用 FastAPI 做审批接口：agent 暂停后，调用 `POST /approve/{run_id}` 继续执行。

**通关标准：**
1. 说出 `create_agent` 替你隐藏了哪 3 件你之前手写的事。
2. 讲清 LangChain v1 和 LangGraph 的分工：什么时候 `create_agent` 就够了，什么时候必须下沉到 LangGraph。
3. 对比 `HumanInTheLoopMiddleware` 和手写的 LangGraph 审批节点，说出各自的优缺点。
4. 调用审批接口后，agent 能从断点继续，而不是从头开始。

## Day 13｜OpenAI Agents SDK + 评估 + 可观测性

**上午：**
- 仓库：https://github.com/openai/openai-agents-python ；文档：https://openai.github.io/openai-agents-python/ （handoffs、guardrails、tracing）
- 《Demystifying evals for AI agents》：https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Hamel Husain《Your AI Product Needs Evals》：https://hamel.dev/blog/posts/evals/
- Hugging Face Agents Course Bonus Unit 2（可观测性与评估）

**下午：**
- 给 D7 的 agent 准备 5 个测试任务，写批量运行脚本，统计成功率作为基线。

**晚上（加练）：**
- LangSmith：https://smith.langchain.com （文档入口在 docs.langchain.com 顶部导航），给 D12 的 LangChain 版本 agent 开启 tracing，和 OpenAI Agents SDK 的 tracing 对比。

**通关标准：**
- 有一个可重复运行的评估脚本，并记录下基线成功率。
- 能在 LangSmith 里定位到 agent 某一步的完整输入和输出。

## Day 14｜升级 agent + 第二周复盘

**上午：**
- 把这周学到的设计加到自己的 agent 上：
  - 工具输出截断（SWE-agent）
  - repo map（Aider）
  - 事件日志（OpenHands）
  - 稳定性处理：超时、429 和 5xx 的指数退避重试
- 参考资料：
  - httpx Timeouts：https://www.python-httpx.org （Timeouts 章节）
  - Tenacity：https://tenacity.readthedocs.io （`retry`、`stop_after_attempt`、`wait_exponential`、`retry_if_exception_type`）
  - Claude API 文档中的 Errors 和 Rate limits 页面
- 加练：写一个自定义 LangChain 中间件，把你的"最大步数限制"或"输出截断"移植进去。

**下午（加练）：**
- 写对比笔记：mini-swe-agent、SWE-agent、Aider、OpenHands 在工具设计和上下文管理上的取舍。

**晚上：** 缓冲时间。

**通关标准：**
- 升级后的 agent 在 5 个测试任务上的成功率高于 D13 的基线。
- 人为制造一次失败（比如设置极短的超时），agent 能自动重试并最终成功。

---

# 第 3 周：记忆、MCP、Web3、毕业项目

## Day 15｜Embedding 与记忆

**上午：**
- MemGPT 论文：https://arxiv.org/abs/2310.08560
- Letta：https://github.com/letta-ai/letta ；文档：https://docs.letta.com
- OpenAI Embeddings 指南：https://platform.openai.com/docs/guides/embeddings
- Sentence Transformers：https://sbert.net （本地免费跑 embedding）
- Pinecone Learn：https://www.pinecone.io/learn/ （搜索 chunking strategies）

**下午（自己写）：**
- 最小的"文本存入 → 语义检索"程序，测试不同 chunking 方式的效果。
- 给你的 agent 实现 MemGPT 式自编辑记忆：让它通过工具自己决定什么信息存入长期记忆。

**晚上（加练）：**
- 用 LangChain 的 embeddings 和 vector store 接口重写检索程序，对比和徒手版本的差异。

**通关标准：**
- 说清 core memory 和 archival memory 各解决什么问题。
- 你的 agent 能在新会话中召回上一次存入的信息。

## Day 16｜JSON-RPC + MCP + TypeScript 工程准备

**上午：**
- JSON-RPC 2.0 规范：https://www.jsonrpc.org/specification （请求、响应、错误、通知）
- 以太坊 JSON-RPC：https://ethereum.org/zh/developers/docs/apis/json-rpc/
- MCP 官网：https://modelcontextprotocol.io （入门介绍、核心架构、规范中的 Transports 章节）
- MCP Python SDK：https://github.com/modelcontextprotocol/python-sdk
- MCP TypeScript SDK：https://github.com/modelcontextprotocol/typescript-sdk
- 官方 server 示例：https://github.com/modelcontextprotocol/servers （挑 filesystem 等简单的读）
- 《Code execution with MCP》：https://www.anthropic.com/engineering/code-execution-with-mcp
- DeepLearning.AI 短课：https://www.deeplearning.ai/short-courses/mcp-build-rich-context-ai-apps-with-anthropic/

**下午：**
- 写一个 MCP server，提供"查询地址 ETH 余额"工具，接入你的 agent。

**晚上：**
- Bun：https://bun.sh/docs （`bun install`、`bun run`、Workspaces）
- pnpm Workspaces：https://pnpm.io/workspaces
- clone ElizaOS 并成功安装依赖。

**通关标准：**
- 你的 agent 能通过 MCP 调用余额查询工具。
- 把一条 MCP 工具调用消息和一条 `eth_getBalance` 请求并排放在一起，指出结构上的相同点。
- ElizaOS 在本地能运行起来。

## Day 17｜ElizaOS

**上午：**
- 仓库：https://github.com/elizaOS/eliza 。运行时核心在 packages/core，包括 agent 循环、插件模型、消息/记忆/状态原语，从这里入手，文档链接在 README 里。

**下午：**
- 插件注册表：https://github.com/elizaOS-plugins/registry ，挑一个链上相关插件（比如 EVM 插件）。
- 插件可以注册 actions、providers、evaluators、services 等。搞清楚这几类概念分别在做什么，画出一条消息从进入到回复的完整路径。

**通关标准：** 说清 actions、providers、evaluators 的区别，并各举一个链上场景的例子。

## Day 18｜链上工具层 + 安全

**上午：链上工具层**
- GOAT SDK：https://github.com/goat-sdk/goat
- Coinbase AgentKit：https://github.com/coinbase/agentkit
- viem：https://viem.sh ；`simulateContract`：https://viem.sh/docs/contract/simulateContract
- ERC-4337：https://eips.ethereum.org/EIPS/eip-4337
- Tenderly 交易模拟：https://docs.tenderly.co/simulations

**下午：安全**
- OWASP Top 10 for LLM：https://genai.owasp.org/llm-top-10/ （Prompt Injection、Excessive Agency、Sensitive Information Disclosure）
- Simon Willison prompt injection 系列：https://simonwillison.net/series/prompt-injection/
- 《The lethal trifecta》：https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/
- 动手：写安全设计文档，作为毕业项目的规范，覆盖 7 项：私钥隔离、交易模拟、金额上限、地址白名单、人工确认、session key、prompt injection 防护。

**通关标准：**
- 说清 GOAT 和 AgentKit 是怎么让私钥远离模型上下文的。
- 安全文档覆盖全部 7 项，并用"lethal trifecta"框架分析你的毕业项目。

## Day 19｜毕业项目（一）：只读版

**上午：**
- FastAPI 教程：https://fastapi.tiangolo.com/zh/tutorial/ （依赖项、安全性、后台任务、测试）
- FastAPI 全栈模板：https://github.com/fastapi/full-stack-fastapi-template （只看 `backend/` 目录结构）

**下午 + 晚上（自己写）：** 链上分析 agent
- 后端用 FastAPI：流式对话接口（SSE）、依赖注入做 API key 鉴权
- 工具通过 MCP 提供（复用 D16）
- 包含"查询余额 / 交易记录"和"模拟交易"两类工具
- 包含最大步数、工具输出截断、重试、事件日志、D15 的长期记忆
- 用 D13 的方法写 5 个测试任务；用 TestClient 给接口写测试

**通关标准：**
- 只读版通过全部 5 个测试任务。
- 所有接口都有 TestClient 测试；没有 API key 的请求会被拒绝。

## Day 20｜毕业项目（二）：testnet 写操作

- 加入 testnet 转账功能，严格按照 D18 的安全文档实现：交易模拟、金额上限、白名单、人工确认，最后加 session key。
- 人工确认通过 FastAPI 审批接口实现（复用 D12 的模式）。
- 新增 3 个安全测试任务，例如"用户诱导转账到白名单外的地址"，验证 agent 会拒绝。

**通关标准：** 8 个测试任务全部通过，其中 3 个安全测试 agent 都正确拒绝了。

## Day 21｜收尾

**上午：** 缓冲时间。

**下午：**
- 加练：把毕业项目的核心能力包装成一个 ElizaOS 插件。
- 打包部署：FastAPI 部署文档 https://fastapi.tiangolo.com/zh/deployment/ （容器中的 FastAPI 一节），把项目打包成 Docker 镜像。
- 写 README：架构图、设计取舍、每个设计借鉴自哪个项目。
- 开源到 GitHub，写一个技术 thread 讲清设计思路。

**晚上：**
- 《Effective harnesses for long-running agents》：https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- 《Building a C compiler with a team of parallel Claudes》：https://www.anthropic.com/engineering/building-c-compiler
- 总复盘：重新回答 Day 1 的问题"workflow 和 agent 怎么选"，对比三周前的答案。

**通关标准：** 项目已开源，能用 Docker 一条命令启动，README 完整，你能在 5 分钟内向别人讲清楚整个架构。

---

# 有意不包含的内容

- **LlamaIndex、CrewAI、AutoGen 等框架**：概念与已学框架高度重叠，学完这条路线后半天就能上手。
- **向量数据库深入使用**：D15 理解原理就够了，选型等项目需要时再学。
- **模型微调和训练**：另一个方向，做 agent 不需要。
- **Kubernetes、云部署**：Docker 已经足够让项目跑起来。
- **前端界面**：你本身就会，需要的话直接用熟悉的技术栈。

判断标准：**它是不是读懂高手项目、或者完成毕业项目所必需的？**

---

计划已经全部排好。下一步从 Day 0 的六项自检开始，做完后把结果发给我。
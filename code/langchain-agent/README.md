# 智扫通售后客服 agent（LangChain 1.x 学习项目）

用一个真实业务场景，把 LangChain 的 **Models、Messages、Tools、Agents** 四个模块从头到尾用一遍。

> 第一次学习这个项目：请按下面的 **「学习顺序」** 一个一个看，每个阶段看完跑对应的练习脚本，再进入下一阶段。

业务：扫地机器人品牌的售后客服。用户可以
- 问使用、故障、保养问题 → 检索实验6 的 Chroma 知识库，回答时附上出处
- 查自己的订单和物流 → 只能查自己的（身份来自登录信息，模型改不了）
- 问是否在保、能否退换 → 由代码按保修规则计算，不让模型推算日期
- 报修 → 生成维修工单，**提交前需要客服人工审批**
- 客服主管还可以修改工单状态（普通用户的模型根本看不到这个工具）

## 目录结构

```
langchain-agent/
├─ main.py                 程序入口：命令行多轮对话
├─ config/                 只放可调参数，改参数不用动代码
│  ├─ model.yml            模型名、temperature、max_tokens、timeout、重试、备用模型、向量模型
│  ├─ agent.yml            调用次数上限、摘要门槛、需要审批的工具、角色可用工具、数据文件位置
│  ├─ chroma.yml           知识库地址、集合名、返回条数、相关性阈值
│  └─ prompts.yml          提示词文件登记表
├─ prompts/                提示词正文（system_prompt.txt、session_summary.txt）
├─ data/                   模拟业务数据：users.json、orders.json、warranty_rules.json
│  └─ runtime/             运行时生成的工单（不提交 git）
├─ services/               业务逻辑：查订单、算保修、建工单、检索知识库、生成会话小结
├─ agent/
│  ├─ agent.py             create_agent 组装 + 会话运行（流式输出、审批暂停/继续）
│  ├─ middleware.py        自定义中间件：动态提示词、按角色筛工具、token 统计、工具异常处理
│  ├─ state.py             State（current_order_id、token_usage）和 Context（user_id、role）
│  ├─ schemas.py           Pydantic：工具参数校验、结构化输出格式
│  └─ tools/               工具：知识库、订单保修、工单
├─ model/factory.py        init_chat_model 统一创建模型（懒加载）
├─ utils/                  读 yml、读提示词、路径、日志、读 .env（来自实验6）
├─ lessons/                四个模块的练习脚本，专门把中间过程打印出来
└─ tests/                  单元测试 + 用假模型的 agent 流程测试（不需要 key）
```

分层的原因：**工具只是一层薄包装，业务规则都在 services 里**。同一个「查订单」以后给网页接口用也不用改；
权限、保修、工单规则可以用普通单元测试保证正确，不依赖模型。

## 学习顺序（从上往下，一个一个看）

原则：**先看不依赖 LangChain 的基础和业务代码，再按 Models → Messages → Tools → Agents 往上看**。每个阶段看完，跑一下对应的练习脚本，对照输出理解。一个阶段没看懂，先别往下走。

### 第 0 步：先整体跑一遍（10 分钟）
1. `README.md`（本文件）：知道项目是干什么的
2. 运行 `python main.py`，以张三登录，试试下面「main.py 里可以试的对话」，先有个直观印象

### 第 1 阶段：配置、提示词、数据（只是文本，没有 Python 逻辑）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 1 | `config/model.yml` | 模型名、temperature、max_tokens 这些参数是什么意思 |
| 2 | `config/agent.yml` | 调用次数上限、哪些工具要审批、不同角色能用哪些工具 |
| 3 | `config/chroma.yml` | 知识库地址、返回几条（k）、相关性阈值（max_distance） |
| 4 | `config/prompts.yml` → `prompts/system_prompt.txt` | 客服的身份和规矩；`{user_name}` 这类占位符之后由代码填进去 |
| 5 | `data/users.json`、`data/orders.json`、`data/warranty_rules.json` | 有哪些用户、订单、保修规则（后面的代码都在查这些） |

### 第 2 阶段：基础工具 utils/（读配置、读提示词、日志）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 6 | `utils/path_tool.py` | 怎么拿到项目里文件的绝对路径 |
| 7 | `utils/env_loader.py` | 怎么读取 `.env` 里的 API key |
| 8 | `utils/config_handler.py` | 第 1 阶段的 yml 是怎么变成 Python 字典的 |
| 9 | `utils/prompt_loader.py` | 提示词 txt 是怎么读进来的 |
| 10 | `utils/logger_handler.py` | 控制台和 logs/ 里的日志是怎么来的 |

### 第 3 阶段：业务规则 services/（普通 Python，和模型无关）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 11 | `services/errors.py` | 三种业务异常：找不到 / 没权限 / 违反规则 |
| 12 | `services/data_store.py` | 怎么读写 JSON 数据 |
| 13 | `services/user_service.py` | 查用户 |
| 14 | `services/order_service.py` | 查订单，以及「只能查自己的订单」是怎么检查的 |
| 15 | `services/warranty_service.py` | 保修是怎么用代码算出来的 |
| 16 | `services/ticket_service.py` | 建工单的规则：已签收、防重复、状态怎么流转 |
| 17 | `services/kb_service.py` | 知识库检索的三步：① 召回 10 条 → ② 重排 → ③ 只留最相关的 3 条；距离和相似度的区别 |
| 17+ | `services/rerank_service.py` | 重排（rerank）：为什么向量检索之后还要再「精排」一次、重排失败时怎么兜底 |
| ✅ | 练习：`python -m pytest -q tests/test_services.py tests/test_kb_rerank.py` | 看业务规则和「召回 → 重排」的测试是怎么写的（需先 `pip install pytest`） |

### 第 4 阶段：Models（模型）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 18 | `model/factory.py` | `init_chat_model` 怎么用 model.yml 的参数创建模型 |
| 19 | `services/summary_service.py` | 模型的 `with_structured_output`：让模型按固定格式输出 |
| ✅ | 练习：`python lessons/01_models.py` | 参数对比、token 统计、流式输出、报错分类 |

（`model/multimodal_embeddings.py` 是向量模型的适配器，可以先跳过）

### 第 5 阶段：Messages（消息）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 20 | `lessons/02_messages.py` | 先运行再读：四种消息、手写一遍「模型 → 工具 → 模型」的循环、tool_call_id |
| ✅ | 练习：`python lessons/02_messages.py` | 对照输出看每条消息长什么样 |

### 第 6 阶段：Tools（工具）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 21 | `agent/schemas.py` | 工具参数的格式要求（比如订单号必须是 SO+8 位数字） |
| 22 | `agent/state.py` | 先只看 `UserContext`：登录身份怎么传给工具 |
| 23 | `agent/tools/order_tools.py` | `@tool` 怎么定义工具；工具只是薄薄一层，真正干活的是 services |
| 24 | `agent/tools/kb_tools.py` | 知识库检索工具；`content_and_artifact` 是什么 |
| 25 | `agent/tools/ticket_tools.py` | 工单工具；`return_direct` 是什么 |
| 26 | `agent/tools/__init__.py` | 所有工具的清单 `ALL_TOOLS` |
| ✅ | 练习：`python lessons/03_tools.py` | 不需要 key，看模型「看到」的工具说明、参数校验、权限隔离 |

### 第 7 阶段：Agents（把前面全部组装起来）
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 27 | `agent/state.py` | 再看 `CustomerServiceState`：对话过程中会变的数据 |
| 28 | `agent/middleware.py` | 中间件：拼提示词、按角色筛工具、统计 token、工具报错处理 |
| 29 | `agent/agent.py` | `create_agent` 怎么把模型、工具、中间件、记忆组装起来；会话怎么流式输出、怎么暂停审批 |
| ✅ | 练习：`python lessons/04_agents.py` | 流式输出、多轮记忆、人工审批、调用次数限制、对话摘要 |
| 30 | `main.py` | 最后看入口：怎么把上面这一切变成命令行对话 |

### 第 8 阶段（可选）：测试
| 顺序 | 文件 | 重点看什么 |
|---|---|---|
| 31 | `tests/fakes.py` | 假模型：不花钱、按剧本回答，用来测试 agent 流程 |
| 32 | `tests/conftest.py`、`tests/test_agent_flow.py` | 怎么在不调用真模型的情况下测试整个 agent |

## 四个模块在代码里的位置

| 模块 | 主要代码 | 练习脚本 |
|---|---|---|
| Models | `model/factory.py`、`config/model.yml`、`services/summary_service.py` | `lessons/01_models.py`：参数对比、token、stream/batch、结构化输出、报错分类 |
| Messages | `agent/agent.py` 的 `_run`、`main.py` 的 `/history` | `lessons/02_messages.py`：手写工具循环、tool_call_id、artifact、add_messages |
| Tools | `agent/tools/`、`agent/schemas.py`、`agent/middleware.py` 的 `guard_tool_call` | `lessons/03_tools.py`：schema、参数校验、context 隔离、Command、return_direct |
| Agents | `agent/agent.py`、`agent/middleware.py`、`agent/state.py` | `lessons/04_agents.py`：stream 模式、多轮记忆、人工审批、response_format、限流、摘要 |

## 运行

**用 PyCharm 打开本项目的方式（重要）**：`File → Open` 选择 `code\langchain-agent` 这个文件夹，单独作为一个项目打开（选 New Window），
不要在 `E:\agent学习任务` 这个大文件夹里运行本项目的代码。
原因：实验6（lab06-rag-customer-service）也有同名的 `utils/`、`model/` 文件夹，两个项目在同一个 PyCharm 窗口里都设为 Sources Root 时，
PyCharm 运行文件可能会导入到另一个项目的同名模块，报 `ImportError: cannot import name 'model_conf' from 'utils.config_handler'`。
本项目的 `.idea/` 已经配置好：项目根目录就是 Sources Root，解释器是共用的 `E:\agent学习任务\.venv`（Python 3.12 (agent学习任务)），打开即可用。

终端进入本目录（`.venv` 已激活）：

```powershell
# 1. 依赖（和实验6 一样，装过就跳过）
python -m pip install -r requirements.txt

# 2. 不需要 key 的测试：业务规则 + agent 流程
python -m pytest -q tests

# 3. 不需要 key 的练习
python lessons/03_tools.py

# 4. 需要 DEEPSEEK_API_KEY 的练习（--part N 只跑某一节）
python lessons/01_models.py
python lessons/02_messages.py
python lessons/04_agents.py

# 5. 正式运行客服
python main.py
```

`.env` 沿用 `E:\agent学习任务\.env`（程序会从项目目录向上查找），需要 `DEEPSEEK_API_KEY`；
问知识库类问题还需要 `DASHSCOPE_API_KEY` 和 `CHROMA_HOST`。

## main.py 里可以试的对话

以 **张三** 登录：
1. `扫地机器人总是迷路怎么办` → 检索知识库，末尾显示参考资料文件名
2. `我有哪些订单` → 只列出张三的 3 个订单
3. `SO20261018 到哪了` → 物流进度
4. `帮我查一下 SO20250601` → 这是李四的订单，会被拒绝
5. `SO20251015 那台吸力变小了，还在保吗` → 2025-10-15 购买，主机保修 12 个月，已过保
6. `SO20260312 拖地漏水，帮我报修` → 判断保修 → 创建工单时暂停，等你输入 y/n 审批
7. `/state`、`/history`、`/summary` 查看 State、消息链、结构化会话小结

以 **王主管** 登录：`把工单 TK…… 改成处理中`（会触发审批）

## 版本记录

<!-- 【v2 网页版】新增这一节 -->

| 版本 | 内容 | 怎么启动 | Git |
|---|---|---|---|
| v1 命令行版 | main.py：命令行里选用户、提问、审批；记忆存在内存（InMemorySaver） | `python main.py` | 标签 `v1-cli` |
| v2 网页版（进行中） | webapp/：FastAPI 后端 + React 前端；记忆存在 SQLite（重启不丢）；阶段 1 已完成：网页能问能答；阶段 2 已完成：回答逐字流式显示（SSE），工具调用实时出现；阶段 3 已完成：审批卡片可以「批准执行 / 拒绝」，生成中可以「停止」；阶段 4 已完成：左侧会话列表，切换、刷新后聊天记录还在，可以删除会话；阶段 5 已完成：「生成小结」卡片（存库、过期提示）、「消息链」调试面板；阶段 6 已完成：检索知识库时实时显示进度（召回 → 重排）| 见 [webapp/README.md](webapp/README.md) | `git log` 里的「阶段 N」提交 |

两个版本共用 agent/、services/、config/，命令行版继续能用，可以对照学习。想看 v2 改了哪些旧文件：`git diff v1-cli --stat`。

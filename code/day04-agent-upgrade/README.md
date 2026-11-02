# Day 4：把 agent 升级到"能上线"的写法

Day 7 的订单 agent 能跑，但离真实产品还差几样东西：参数和输出要有**可靠的结构**，回答要能**一边生成一边显示**，多个请求要能**同时处理**，重复的提示词要**省钱**，最后还要变成一个**能被前端调用的服务**。Day 4 就是补这五块：

| 能力 | 解决什么问题 | 对应文件 |
|---|---|---|
| Pydantic | 工具参数、模型输出的格式不可靠 | `tools.py`、`01` |
| 结构化输出 | 代码要读模型的判断结果，必须是固定格式的 JSON | `ticket.py`、`02` |
| 流式输出 | 用户干等好几秒才看到第一个字 | `03` |
| asyncio 并发 | 10 条工单一条条处理太慢 | `04` |
| 提示词缓存 | 每一步都重发长长的 system 提示词，又慢又贵 | `05` |
| FastAPI 服务 | agent 只能在终端里跑，前端用不了 | `server.py`、`06` |
| 故障演练 | 前面全是"一切正常"，真实项目大部分时间在处理不正常 | `07` |

---

## 0. 运行前准备

所有命令都在**项目根目录** `E:\agent学习任务` 下执行（PyCharm 里打开 Terminal，默认就在这里）。

```powershell
# 1. 用项目自己的虚拟环境（PyCharm 的解释器也要选 .venv）
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 确认 .env 里有 DEEPSEEK_API_KEY=...（common.py 会自动读取，不要把 key 写进代码）

# 3. Windows 终端中文乱码时，先执行这一句
$env:PYTHONIOENCODING="utf-8"
```

费用：除了 01 和 07 的 mock 部分，其他脚本都会调用真实 API。全部跑一遍大约几万 tokens，按 DeepSeek 价格是几分钱的量级。

## 1. 文件地图：谁依赖谁

```
common.py      配置：读 .env、创建同步/异步客户端、订单数据、10 条模拟工单
   │
   ├── tools.py    3 个查询工具（Pydantic 参数模型 + 函数 + 注册表 + 统一执行入口）
   │      │
   │      └── ticket.py   工单分析：输出结构 TicketAnalysis + 提示词 + 校验 + 重试（同步/异步两版）
   │
   ├── 01 ~ 05、07   演示脚本：每个只讲一个知识点，都 import 上面三个模块
   └── server.py     把 tools + ticket + 流式 agent 包装成 HTTP 接口；06 是它的调用方
```

这种分法和真实项目的思路一样：**可复用的逻辑放模块里（common / tools / ticket），演示和入口放脚本里**。脚本之间不互相 import。

建议的阅读和运行顺序：`common.py → tools.py → 01 → ticket.py → 02 → 03 → 04 → 05 → server.py + 06 → 07`

---

## 2. 逐个拆解

每一节都按这个顺序讲：**要解决的问题 → 关键代码 → 怎么看输出（用 `run_logs/` 里的真实结果） → 容易踩的坑**。

### 2.1 `tools.py` + `01_pydantic_tools.py`：用 Pydantic 定义工具

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\01_pydantic_tools.py
```
不调用 API，不花钱。

**问题**：Day 7 里同一个工具要写两遍：一遍手写 JSON Schema 发给模型，一遍用 jsonschema 校验参数，而且 `json.loads` 还要单独 try。两份很容易改了一份忘了另一份。

**关键代码**
- `tools.py:33` `OrderId = Annotated[str, Field(pattern=...)]`：订单号格式只写一次，三个工具共用
- `tools.py:42` `extra="forbid"`：多传字段直接报错，生成 schema 时变成 `additionalProperties: false`
- `tools.py:65` `field_validator(mode="before")`：先把 `" ord100021 "` 规范成 `"ORD100021"`，避免模型因为大小写白白失败一次
- `tools.py:118` `REGISTRY`：工具名 → (参数模型, 函数)。加新工具只改这里
- `tools.py:135` `TOOLS`：用 `model_json_schema()` **自动生成**发给模型的 schema。所以项目里没有单独的 .json schema 文件，Python 类就是唯一来源
- `tools.py:156` `model_validate_json(raw_args)`：一步完成"解析 JSON + 校验 + 变成对象"

**怎么看输出**（`run_logs/01_pydantic_tools.txt`）
- 第 2 部分把 Day 7 手写的 schema 和自动生成的并排打印。差别只有多了 `title`、Optional 变成 `anyOf [..., null]`
- 第 3 部分 10 个用例：3 个通过、7 个被拦截。注意 `type=json_invalid`：坏 JSON 和字段错误走的是同一个 except
- 第 4 部分：参数错误时，`execute_tool_call` 不会让程序崩，而是返回一段错误文字给模型，让它自己改

**坑**
- 字符串 `"99"` 能通过 `float` 字段：Pydantic 默认是宽松模式，会做安全的类型转换。要严格就用 `strict=True`
- 工具函数抛异常时也必须变成文字返回给模型（`tools.py:159-162`），否则一个工具的 bug 就会让整个 agent 崩掉

### 2.2 `ticket.py` + `02_structured_output.py`：让模型输出程序能读的结果

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\02_structured_output.py            # A B C D 全部
.venv\Scripts\python.exe code\day04-agent-upgrade\02_structured_output.py --only D   # 只跑一部分
.venv\Scripts\python.exe code\day04-agent-upgrade\02_structured_output.py --all      # 10 条工单
```

**问题**：客服系统要根据模型的判断**自动分流**（转人工 / 优先处理 / 正常处理）。代码要读 `urgency`、`needs_human` 这些字段，所以输出必须是格式固定的 JSON，而不是一段话。

拿到结构化输出有三个级别，可靠程度依次升高：

| 级别 | 做法 | 保证什么 | 本项目 |
|---|---|---|---|
| 1 | 只在提示词里说"用 JSON 回答" | 什么都不保证 | A 部分（反面教材） |
| 2 | JSON 模式 `response_format={"type": "json_object"}` | 保证是合法 JSON，不保证字段对 | B 部分，主力方案 |
| 3 | 严格模式（按 schema 约束生成） | 字段名、枚举、类型都对 | D 部分（DeepSeek Beta 的 strict 工具调用） |

**关键代码**
- `ticket.py:37` `TicketAnalysis`：期望的输出结构。`Literal` 限定枚举，`Field(ge=1, le=5)` 限定范围
- `ticket.py:65` `SYSTEM_PROMPT`：必须包含 "json" 这个词（DeepSeek 的要求），附上 schema 和一个示例
- `ticket.py:78` `check()`：校验输出，不合格就生成一句"错在哪"的提示
- `ticket.py:97` `analyze_ticket()`：**问 → 校验 → 不合格就把错误输出和错误原因追加进对话再问**，最多 3 次（`MAX_ATTEMPTS`）
- `02:route()`：拿到结构化结果后，分流就是几行 if，这就是结构化输出的意义

**怎么看输出**（`run_logs/02_structured_output.txt`、`02_part_D.txt`）
- A：模型在 JSON 外面包了 ```` ```json ```` 代码块，还自己起了中文字段名 → `json.loads` 直接失败
- B：4 条工单都是第 1 次就通过，合计输入 1783 / 输出 207 tokens。每条输入约 450 tokens，大头是 system 里的 schema
- C：人为塞一个错误答案（intent 不在枚举里、urgency=9、缺字段），模型看到错误提示后第 2 次就改对了
- D：严格模式下服务端接受了 schema，4 条全部通过；合计输入 2195 / 输出 519，比 B 贵（工具定义 + 工具调用格式的开销）

**坑**
- JSON 模式下 `max_tokens` 太小，JSON 会被截断（见 07 的演练 4）
- 严格模式不支持 `maxLength`，所以 `summary` 的 40 字上限只能靠 Pydantic 事后检查。**服务端约束 + 本地校验两层都要有**
- 每次重试都会重发整段对话，tokens 是累加的

### 2.3 `03_streaming.py`：流式输出

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\03_streaming.py
```

**问题**：模型是一个 token 一个 token 生成的。不开流式，要等全部生成完才返回，用户盯着空白等。

**关键代码**
- `03:48-51` `stream=True` + `stream_options={"include_usage": True}`：create() 立刻返回一个迭代器；加上 include_usage，最后一个 chunk 才会带 token 用量
- `03:59` 流式里读的是 `delta.content`（增量），不是 `message.content`
- `03:99` 工具调用也是碎片：第一个碎片带 id 和函数名，后面只带 arguments 的一小段字符串，必须按 `index` 拼完才是合法 JSON

**怎么看输出**（`run_logs/03_streaming.txt`）
- A：非流式 1.21s 后一次性出现；流式第一个字 0.43s 就出现，总耗时 0.94s。**总时间差不多，但首字时间（TTFT）短得多**，这才是用户感受到的"快"
- B：能看到 `arguments片段='{'`、`'email'`、`'@'` 这样一小段一小段地来；第 2 步模型一次发了两个 `check_refund_policy` 调用（并行工具调用，index 不同）

**坑**
- 单个碎片不是合法 JSON，不能收到一段就 `json.loads`
- 流式时文字可以实时显示，但工具调用必须收完整再执行
- 最后那个 usage chunk 的 `choices` 是空列表，不跳过会报 IndexError（`03:84`）

### 2.4 `04_async_concurrency.py`：并发处理

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\04_async_concurrency.py
.venv\Scripts\python.exe code\day04-agent-upgrade\04_async_concurrency.py --n 5   # 只用 5 条，省时间
```

**问题**：调用 LLM 时，程序大部分时间在等网络，CPU 闲着。一条条处理，总时间 = 每次等待相加。

**关键代码**
- `04:37` `async def` + `await asyncio.sleep`：await 的意思是"我要等了，事件循环先去跑别人"
- `04:47` 反面教材：在 async 函数里用 `time.sleep`，整个事件循环被卡住
- `04:112` `Semaphore(3)`：最多同时 3 个请求，防止一次发几百个被 API 限流（HTTP 429）
- `04:115-116` `gather(..., return_exceptions=True)`：一条失败不拖垮整批
- `ticket.py:123` 异步版 `analyze_ticket_async`：和同步版只差两处，`async def` 和 `await`，客户端必须换成 `AsyncOpenAI`

**怎么看输出**（`run_logs/04_async_concurrency.txt`）
- A：顺序 3.03s → gather 1.01s → gather 但里面用 time.sleep 又变回 3.00s
- B：10 条真实工单，顺序 9.01s，并发 2.60s，快 3.5 倍。注意看时间戳："开始"最多同时 3 个，完成顺序是乱的，但 `results` 的顺序和输入一致

**坑**
- async 函数里用同步 OpenAI 客户端，看起来并发了，实际上还是一个个来（和 time.sleep 一样）
- 并发数不是越大越好：受 API 速率限制和费用限制，生产环境一般可配置

### 2.5 `05_prompt_cache.py`：提示词缓存

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\05_prompt_cache.py
```

**问题**：API 是无状态的，agent 每一步都要把 system 提示词 + 工具说明 + 全部历史重发一遍。DeepSeek 会自动缓存"前缀"，命中部分更便宜也更快，前提是**开头完全一样**。

**关键代码**
- `05:42` `SYSTEM`：店铺规则 + 全部订单数据，故意做得很长（约 1400 tokens）
- `05:45` `cache_stats()`：从 `usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens` 读命中情况
- `05:91` 时间戳：用来演示"变化的内容放在哪里"

**怎么看输出**（`run_logs/05_prompt_cache.txt` 末尾的汇总表）

| 请求 | 命中率 | 说明 |
|---|---|---|
| 1 第一次 | 0%～85% | 全新的提示词是 0%；之前几分钟内跑过同样的内容，缓存还在，第一次就会命中 |
| 2 完全重复 | 85% | 前缀命中 |
| 3、4 换问题 | 85% | system 一样，就能复用 |
| 5 时间戳放开头 | **0%** | 第一个字就不同，整段失效 |
| 6 时间戳放末尾 | 92% | 前面全部命中 |
| 7 多轮对话 | 88% | 之前的对话都是前缀 |

**坑 / 对 agent 设计的启发**
- system 提示词和工具列表要保持稳定：不要塞时间戳、不要每次重新排序工具
- 历史消息只追加、不修改
- 第二次运行时，第 1 个请求也可能直接命中（缓存还在），这是正常的

### 2.6 `server.py` + `06_call_server.py`：变成 HTTP 服务

需要**两个终端**：

```powershell
# 终端 1：启动服务（PyCharm 里直接运行 server.py 也可以），看到 Uvicorn running on http://127.0.0.1:8000 就好了
.venv\Scripts\python.exe code\day04-agent-upgrade\server.py

# 浏览器打开 http://127.0.0.1:8000/docs ，可以直接点 Try it out 测接口

# 终端 2：用代码调用各个接口
.venv\Scripts\python.exe code\day04-agent-upgrade\06_call_server.py

# 用完回到终端 1 按 Ctrl+C 停止服务
```

**问题**：真实产品里 agent 是后端服务，前端发 HTTP 请求过来。

**接口一览**
| 接口 | 写法 | 复用了哪部分 |
|---|---|---|
| `GET /orders/{id}` | 普通 def | tools.py |
| `POST /tickets/analyze` | async def | ticket.py（02） |
| `POST /tickets/analyze-batch` | async def + Semaphore | 04 的并发 |
| `POST /chat` | 流式 SSE | 03 的流式 + 工具调用 |
| `GET /demo/*` | 三种写法对比 | def vs async def |

**关键代码**
- `server.py:54` `lifespan`：启动时创建一个 AsyncOpenAI 客户端，所有请求共用，关闭时释放。不要每个请求 new 一个
- `server.py:66` 请求模型：`Field(min_length=1)`，空字符串进来 FastAPI 直接返回 422，函数根本不执行
- `server.py:124` 重试用完返回 502：表示"上游（模型）没给出合格结果"，而不是笼统的 500
- `server.py:156` `agent_events`：异步生成器，每 `yield` 一次就推给前端一条 `data: {...}`（SSE 格式）
- `server.py:206` 流开始后出错，状态码 200 已经发出去了，只能发一个 `error` 事件

**怎么看输出**（`run_logs/06_call_server.txt`）
- 第 1 部分：同时发 5 个"等 1 秒"的请求，`async-await` 1.01s、`sync` 1.02s、`async-blocking` **5.01s**。最糟糕的组合就是在 async def 里调用阻塞代码
- 第 2 部分：错误参数被自动拦成 422，不存在的订单是 404，正常是 200
- 第 4 部分：`/chat` 真的是流式，实测 97 个文字片段在 0.65s ~ 1.55s 之间陆续到达

**def 还是 async def？**
- 函数里要 `await` 东西（AsyncOpenAI、httpx.AsyncClient、异步数据库）→ `async def`
- 函数里调用的是同步阻塞的库（requests、同步 OpenAI、time.sleep）→ 普通 `def`，FastAPI 会放进线程池
- **绝对不要**：async def 里调同步阻塞代码

**坑**
- 06 连不上服务：先确认终端 1 的服务还开着；系统开了代理时，06 里 `trust_env=False` 就是为了绕过代理
- 端口 8000 被占用：上次的服务没关掉，关掉那个终端或换端口

---

## 3. 故障演练：`07_failure_drills.py`

```powershell
.venv\Scripts\python.exe code\day04-agent-upgrade\07_failure_drills.py            # 全部 8 个
.venv\Scripts\python.exe code\day04-agent-upgrade\07_failure_drills.py --case 4   # 只跑一个
```

[mock] 用的是假客户端，结构和 SDK 返回的对象一样，但内容由我们写死：不联网、不花钱、结果可控。这也是写单元测试的基本方法。

| # | 模拟的问题 | 实际表现（`run_logs/07_failure_drills.txt`） | 正确的处理方式 |
|---|---|---|---|
| 1 | API key 错误 | `AuthenticationError` 401 | 不要重试；启动时做健康检查，尽早暴露 |
| 2 | 模型名写错 | `BadRequestError` 400 | 4xx 是请求本身的问题，改配置，不重试 |
| 3 | 请求超时 | `max_retries=0` 0.11s 报错；`=2` 1.61s 才报错 | SDK 默认超时 600s、自动重试 2 次；在线服务要把超时调短 |
| 4 | max_tokens 太小 | `finish_reason=length`，JSON 断在一半，`Invalid JSON` | 重试没用，要调大 max_tokens；日志里要记 finish_reason |
| 5 | 前两次输出不合格 | 空内容 → 字段错 → 第 3 次通过 | 把错误原因反馈给模型；注意 tokens 是 3 倍 |
| 6 | 一直不合格 | 调用 3 次后抛 `TicketParseError` | 重试要有上限；失败后转人工 / 返回 502 |
| 7 | 并发时一条失败 | 不加 `return_exceptions`：整批报错，4 条成功的也拿不到 | 加 `return_exceptions=True`，失败的单独重跑 |
| 8 | 流式中途断开 | 前半句已经显示，收不回来 | 发 error 事件，前端提示"回答中断"；记日志 |

**错误分两类**，这是工程上处理异常的核心思路：
- **改代码/配置才能好**（401、400、max_tokens 太小）：重试没意义，要尽快失败、报清楚原因
- **等一下可能就好**（超时、连接断开、429、5xx、模型偶尔输出不合格）：有上限地重试，最后要有兜底

### 一次真实的"换模型"事故（2026-10-19）

这是做故障演练时碰到的真实问题，比上面的模拟更有代表性：

1. **发现**：演练 2 的报错信息说，DeepSeek 当前支持的模型名是 `deepseek-flash` 和 `deepseek-v4-pro`。我们原来用的 `deepseek-chat` 还能调用，但很可能是旧别名，迟早下线。
2. **直接换**：只改了模型名，用 `AGENT_MODEL=deepseek-flash` 把 Day 4 全部跑一遍，结果出了一堆问题：
   - 02 的 D 部分直接被拒绝：`400 Thinking mode does not support this tool_choice`
   - 02 的 A 部分、演练 4 返回**空内容**：输出额度都被"思考"用掉了
   - 02 的 B 部分有一条第 1 次返回空内容，靠重试才救回来；输出 tokens 从 207 涨到 865
   - 03 的首字时间从 0.60s 变成 1.48s，04 的并发总耗时从 3.28s 变成 4.89s
3. **定位原因**：`deepseek-flash` 默认开启**思考模式**，先生成一段推理（`message.reasoning_content`），再生成正式回答。推理也算输出 tokens、也受 `max_tokens` 限制。
4. **修复**：在 `common.py` 里统一定义 `EXTRA_BODY = {"thinking": {"type": "disabled"}}`，每个请求都带上 `extra_body=EXTRA_BODY`。修复后重跑，结果和原来的 `deepseek-chat` 一致（B 部分的 tokens 都是 1783 / 207），所以 `deepseek-chat` 基本可以确定就是"关掉思考的 flash"。

**学到的工程习惯**
- 换模型不是"改个名字"：不同模型的默认行为、支持的参数、token 消耗都可能不一样。换之前要把核心用例全部重跑一遍。这正是 evals（固定测试集）存在的意义
- 模型名、这类开关要集中在一个地方配置（`common.py`），不要散落在各个文件里
- 什么时候该开思考模式：复杂推理、多步规划、难的工具选择可以开（更准，但更慢、更贵）；分类、抽取、简单问答这类任务关掉更合适

---

## 4. 自己动手改一改（检验是否真的理解）

每个练习都只需要改一两行，改完运行，看结果和你预想的是否一致：

1. `ticket.py` 里把 `max_tokens=300` 改成 `30`，运行 02 的 B 部分：会发生什么？重试救得回来吗？（想想演练 4）
2. `04` 里把 `Semaphore(3)` 改成 `Semaphore(1)` 和 `Semaphore(10)`，并发耗时分别是多少？为什么 1 的时候和顺序处理差不多？
3. `05` 里把请求 6 的时间戳放进 system 的**中间**（规则和订单数据之间），命中率会是多少？
4. `server.py` 里把 `/demo/sync` 的 `def` 改成 `async def`（保留 time.sleep），再跑 06，耗时会变成多少？
5. 在 `tools.py` 的 `REGISTRY` 里加一个新工具（比如"查物流"），不改其他任何地方，03 和 /chat 能不能直接用上它？为什么？

## 5. 这一天学完，应该能回答

- 为什么 schema 用 Pydantic 生成，而不是手写 JSON？
- JSON 模式和严格模式各保证了什么、没保证什么？为什么拿到结果后还要再校验？
- 流式输出让什么变快了，什么没变？
- async 函数里调用同步客户端，会发生什么？
- 怎样安排提示词，才能让缓存命中率最高？
- 哪些错误该重试，哪些不该？

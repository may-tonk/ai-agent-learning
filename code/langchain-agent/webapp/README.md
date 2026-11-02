# 网页版（v2）

【v2 网页版新增】智扫通售后客服的网页界面：FastAPI 后端 + React 前端。agent/ 和 services/ 和命令行版共用。

## 启动（开两个终端）

```powershell
# 终端 1：后端，在 code\langchain-agent 下执行
..\..\.venv\Scripts\python.exe -m uvicorn webapp.backend.app:app --port 8001 --reload

# 终端 2：前端，在 code\langchain-agent\webapp\frontend 下执行（第一次要先 npm install，已经装好了）
npm run dev
```

然后用浏览器打开 http://127.0.0.1:5173 （localhost:5173 也可以）。
后端接口文档：http://127.0.0.1:8001/docs （可以直接在页面上试调用接口）。

## 端口和地址

| 服务 | 地址 | 说明 |
|---|---|---|
| 前端（Vite） | 127.0.0.1:5173 | 页面；`/api` 开头的请求由 Vite 转发给后端 |
| 后端（FastAPI） | 127.0.0.1:8001 | 不用 8000，避免和 Ubuntu 上的 Chroma 混淆 |
| 数据（SQLite） | webapp/backend/runtime/app.db | 后端第一次启动时自动创建，不提交 Git。里面有 checkpointer 的存档表（给模型的记忆）、阶段 4 的 threads、messages 表（会话列表、聊天记录）和阶段 5 的 summaries 表（会话小结） |

## 目录（阶段 1 ~ 6）

```
webapp/
├─ backend/
│  ├─ app.py            创建 FastAPI；启动时打开 checkpointer、build_agent()
│  ├─ config/web.yml    CORS、checkpointer（memory / sqlite）
│  ├─ checkpointer.py   按配置创建 InMemorySaver / AsyncSqliteSaver
│  ├─ deps.py           依赖注入：当前用户（X-User-Id 模拟登录）、agent；阶段 4：仓库、会话归属检查
│  ├─ db.py             阶段 4：打开业务库、建 threads / messages 两张表；阶段 5：summaries 表
│  ├─ repositories/     阶段 4：数据层，threads.py（会话表）、messages.py（消息表），路由里不写 SQL；阶段 5：summaries.py
│  ├─ errors.py         阶段 5：模型异常 → HTTP 错误（对话、小结两个接口共用）
│  ├─ schemas.py        接口的请求 / 响应格式
│  ├─ routers/chat.py   POST /api/chat（不流式）、/api/chat/stream（阶段 2：SSE 流式，页面用这个）
│  │                    /api/chat/resume（阶段 3：审批后继续）；停止后下一句前自动补存档
│  ├─ routers/users.py  GET /api/users
│  ├─ routers/threads.py 阶段 4：GET /api/threads 会话列表、/{id}/messages 聊天记录、/{id}/state State、DELETE /{id}
│  │                    阶段 5：/{id}/chain checkpointer 里的原始消息链
│  ├─ routers/summary.py 阶段 5：POST / GET /api/threads/{id}/summary 会话小结（调用 services/summary_service.py）
│  ├─ streaming/        阶段 2：protocol.py 前端事件协议、runner.py 把 v3 事件翻译成前端事件
│  │                    阶段 6：runner.py 订阅 custom 流，工具进度翻译成 tool_progress 事件
│  │                    阶段 4：recorder.py 把一轮的事件拼成一条客服消息，存进消息表
│  └─ tests/            接口测试（假模型，不花钱）：test_api_chat.py、test_api_stream.py、test_api_resume.py（阶段 3）、
│                       test_api_threads.py（阶段 4）、test_api_summary.py（阶段 5）、
│                       test_api_progress.py（阶段 6）
├─ frontend/
│  ├─ package.json、vite.config.js、index.html
│  └─ src/  main.jsx、App.jsx、constants.js、styles.css
│           api/client.js（普通请求；阶段 4：会话列表、历史、State、删除；阶段 5：小结、消息链）、api/sse.js（阶段 2：读流式响应、解析 SSE；阶段 3：resumeChat、停止用的 signal）
│           components/Sidebar.jsx（阶段 4：历史会话列表、State 卡片）、ChatWindow.jsx、MessageBubble.jsx
│           components/SummaryCard.jsx（阶段 5：小结卡片）、ChainPanel.jsx（阶段 5：消息链面板）
└─ scripts/
   ├─ chat_probe.py     命令行调用 /api/chat，排查「后端还是前端的问题」
   ├─ sse_probe.py      命令行调用 /api/chat/stream，打印每条事件的到达毫秒数，验证是不是真流式
   └─ approval_probe.py 阶段 3：真实 DeepSeek 走一遍批准（approve）、拒绝（reject）、停止（stop）
```

## 测试

```powershell
# 在 code\langchain-agent 下执行：根目录 tests/ 和 webapp/backend/tests/ 一起跑
..\..\.venv\Scripts\python.exe -m pytest -q
```

## 常见问题

- **页面提示「加载用户失败」**：后端没启动，或者不在 8001 端口。
- **脚本连 127.0.0.1 失败、浏览器却正常**：检查是不是走了 Clash 代理。chat_probe.py 已经设置了不走代理。
- **提示「这段对话有一个操作在等审批」**：先在审批卡片上点「批准执行」或「拒绝」。阶段 4 起刷新后卡片会跟着聊天记录一起显示回来。
- **阶段 4 之前聊过的会话不在左侧列表里**：会话列表来自阶段 4 新建的 threads 表，之前的对话只在 checkpointer 存档里，没有登记。
- **聊天记录为什么不直接从 checkpointer 读**：checkpointer 是给模型的记忆，对话超过 6000 token 时摘要中间件会把旧消息压缩掉；页面要的是完整记录，所以单独存在 messages 表（见 `backend/db.py` 开头）。
- **检索进度从哪来（阶段 6）**：`agent/tools/kb_tools.py` 用 `get_stream_writer()` 把 `services/kb_service.search` 每一步的进度写进 LangGraph 的 custom 流；`runner.py` 调 `astream_events` 时要加 `transformers=[CustomTransformer]` 才收得到（不加就收不到，实测）。第一次检索要连 Chroma、加载向量模型，召回会慢一些（实测约 2 秒），之后约 0.2 秒。
- **改了前端文件、页面却没变**：一般 Vite 会自动刷新。实测遇到过一次：文件是从别的程序（不是编辑器）改的，Vite 没收到「文件变了」的通知，一直用旧版本。在编辑器里随便改一下再保存，或者重启 `npm run dev` 即可。
- **小结显示「生成之后又有了新消息」**：小结表记着生成时有几条消息，之后又聊过就提示过期，点「重新生成」即可（会再调用一次 DeepSeek）。
- **小结里的工单号从哪来**：从 checkpointer 里的工具结果（创建报修单返回的工单号），所以小结读的是 checkpointer，不是消息表；消息表只存了工具名和参数。
- **点了「停止」之后接着问会不会出错**：不会。后端在下一句开始前，会给没跑完的工具调用补一条结果（`chat.py` 的 `_close_stopped_run`），否则 DeepSeek 会报 400。
- **页面上的回答还是一次性出来的**：先用 `sse_probe.py` 直连后端（`--base http://127.0.0.1:8001`）看文字是不是陆续到达；直连正常、经过 5173 不正常，就是转发层把流攒成了一块。

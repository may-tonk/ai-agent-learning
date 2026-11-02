// 【v2 网页版新增】整个页面的「总管」组件：管理登录用户、当前会话、消息列表，调用后端接口
//
// 【在整体流程里的位置】
//   main.jsx 渲染 <App /> → App 加载用户列表 → 用户在 ChatWindow 里输入并发送
//   → App 的 send() 调用 api/sse.js 的 streamChat → 后端 POST /api/chat/stream
//   → 每收到一条事件（文字片段、工具开始/结束…）就更新 messages → 页面重画，文字一点点长出来（阶段 2）
//   审批卡片上点「批准 / 拒绝」→ decide() 调用 resumeChat → 后端 POST /api/chat/resume，在同一条消息里接着显示（阶段 3）
//   生成中点「停止」→ stop() 中断 fetch → 后端发现浏览器断开，取消这次运行（阶段 3）
//   左侧会话列表点某个会话 → openThread() 读聊天记录和 State → 页面显示历史，接着聊（阶段 4）
//   顶栏「生成小结」→ makeSummary() → 小结卡片；「消息链」→ 右侧面板显示 checkpointer 里的原始消息（阶段 5）
//
// 【React 的核心思路（读这个文件前先记住）】
//   页面 = 根据「状态（state）」画出来的。想改页面，不是去改 HTML，而是改状态（setXxx），React 自动重画。
//   useState(初始值) 返回 [当前值, 修改函数]，例如 const [loading, setLoading] = useState(false)
//
// 和命令行 main.py 的对应关系：
//   choose_user()（选登录用户）    →  左侧边栏的用户列表（components/Sidebar.jsx）
//   /new 命令（换 thread_id）       →  侧边栏的「新会话」按钮
//   /state 命令（看 State）         →  侧边栏底部的「当前会话」卡片（阶段 4 改成读后端 State）
//   render()（打印回答、工具、资料）→  components/MessageBubble.jsx
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  deleteThread,
  fetchHistory,
  fetchSummary,
  fetchThreadState,
  fetchThreads,
  fetchUsers,
  generateSummary,
} from './api/client.js'
import { resumeChat, streamChat } from './api/sse.js'
import ChainPanel from './components/ChainPanel.jsx'
import ChatWindow from './components/ChatWindow.jsx'
import Sidebar from './components/Sidebar.jsx'
import SummaryCard from './components/SummaryCard.jsx'

// localStorage：浏览器提供的小型本地存储（键值对，刷新、关浏览器都还在）。
// 存两样东西：上次选的用户、每个用户当前的 thread_id —— 刷新页面后还能接着同一段对话聊
// 【阶段 4】聊天记录本身存在后端的消息表里；这里只记「上次停在哪个会话」，刷新后自动打开它
const USER_KEY = 'zst.user'
const threadKey = (userId) => `zst.thread.${userId}`

// 读写 localStorage 都包一层 try：浏览器隐私模式或禁用存储时会抛错，不能因此让整个页面挂掉
function readStore(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function writeStore(key, value) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // 存不进去也没关系：只是刷新后要重新开会话
  }
}

export default function App() {
  const [users, setUsers] = useState([]) // 登录下拉框的选项（来自 GET /api/users）
  const [userId, setUserId] = useState('') // 当前登录用户
  const [threadId, setThreadId] = useState(null) // 当前会话 ID；null = 还没开始（发第一句话时后端生成）
  const [messages, setMessages] = useState([]) // 页面上显示的消息：{id, role, text, ...}
  const [loading, setLoading] = useState(false) // 是否在等后端回答（等的时候禁用输入框、显示「正在输入」）
  const [threads, setThreads] = useState([]) // 【阶段 4】左侧会话列表（GET /api/threads）
  const [threadState, setThreadState] = useState(null) // 【阶段 4】当前会话的 State：订单、token、存档消息数
  const [historyLoading, setHistoryLoading] = useState(false) // 【阶段 4】是否正在加载聊天记录
  const [summary, setSummary] = useState(null) // 【阶段 5】当前会话的小结 {summary, created_at, message_count, stale}
  const [summaryBusy, setSummaryBusy] = useState(false) // 【阶段 5】是否正在生成小结
  const [summaryError, setSummaryError] = useState('') // 【阶段 5】生成失败的提示
  const [summaryHidden, setSummaryHidden] = useState(false) // 【阶段 5】小结卡片点了 ×（收起，不是删除）
  const [chainOpen, setChainOpen] = useState(false) // 【阶段 5】「消息链」面板是否打开
  const [loadError, setLoadError] = useState('') // 用户列表加载失败（通常是后端没启动）
  const [sidebarOpen, setSidebarOpen] = useState(false) // 手机窄屏时侧边栏是否展开（宽屏一直显示）
  // useRef：一个「改了不会触发重画」的变量。这里用来给每条消息编号，作为 React 列表的 key
  const nextId = useRef(1)
  // 【阶段 3】当前这次流式请求的 AbortController（「中止器」），「停止」按钮调用它的 abort()。
  //   用 useRef 而不是 useState：它只是一个「遥控器」，换了也不需要重画页面
  const abortRef = useRef(null)
  // 【阶段 4】当前用户和会话的「最新值」。为什么 state 之外还要 ref：
  //   函数里读 state 读到的是「这个函数创建那一刻」的值。例如 send() 开始时 threadId 还是 null（新对话），
  //   流式过程中 run_started 才拿到新的 thread_id，send() 结束时想刷新这个会话的 State，读 threadId 还是 null。
  //   ref 是同一个盒子，任何时候读 .current 都是最新值。
  const userRef = useRef('')
  const threadRef = useRef(null)
  // 【阶段 4】每次打开会话都加 1。加载历史是异步的：快速连点两个会话时，先点的那个可能后返回，
  //   返回时发现编号已经不是自己的了，就丢掉结果，不会把 A 的历史显示到 B 下面
  const openSeq = useRef(0)

  // 【阶段 4】设置当前会话：state、ref、localStorage 三处一起改，不会漏
  function selectThread(id) {
    threadRef.current = id
    setThreadId(id)
    writeStore(threadKey(userRef.current), id)
  }

  // 【阶段 4】重新加载左侧会话列表（发完消息、删了会话之后调用，让标题和排序保持最新）
  function refreshThreads() {
    const uid = userRef.current
    fetchThreads(uid)
      .then((list) => uid === userRef.current && setThreads(list)) // 期间切了用户就不用了
      .catch(() => {}) // 列表刷新失败不影响聊天，下次再刷
  }

  // 【阶段 4】重新读当前会话的 State（侧边栏底部的卡片）
  function refreshState() {
    const tid = threadRef.current
    if (!tid) return setThreadState(null)
    fetchThreadState(userRef.current, tid)
      .then((st) => tid === threadRef.current && setThreadState(st))
      .catch(() => {})
  }

  // 【阶段 5】重新读当前会话的小结（打开会话、每轮对话结束时调用：对话结束后小结可能变成「过期」）
  function refreshSummary() {
    const tid = threadRef.current
    if (!tid) return setSummary(null)
    fetchSummary(userRef.current, tid)
      .then((data) => tid === threadRef.current && setSummary(data))
      .catch(() => {}) // 读不到小结不影响聊天
  }

  // 【阶段 5】清掉小结相关的显示（换会话、开新会话时）
  function resetSummary() {
    setSummary(null)
    setSummaryError('')
    setSummaryHidden(false)
  }

  // 【阶段 5】「生成小结」按钮：调用后端生成（要等几秒），成功后显示卡片；失败显示后端给的提示
  async function makeSummary() {
    const tid = threadRef.current
    if (!tid) return
    setSummaryBusy(true)
    setSummaryError('')
    setSummaryHidden(false)
    try {
      const data = await generateSummary(userRef.current, tid)
      if (tid === threadRef.current) setSummary(data) // 生成期间换了会话就不显示了（已经存进数据库，回来能看到）
    } catch (e) {
      if (tid === threadRef.current) setSummaryError(`生成小结失败：${e.message}`)
    } finally {
      setSummaryBusy(false)
    }
  }

  // 【阶段 4】打开一个会话：先清空页面，再从后端读聊天记录和 State
  async function openThread(id) {
    const seq = ++openSeq.current
    selectThread(id)
    setMessages([])
    setThreadState(null)
    resetSummary() // 【阶段 5】
    setHistoryLoading(true)
    try {
      const history = await fetchHistory(userRef.current, id)
      if (seq !== openSeq.current) return // 加载期间又点了别的会话：这次的结果作废
      // 历史消息的 id 是数据库里的编号，可能和页面自己生成的编号撞上，所以统一换成页面的编号
      setMessages(history.map((m) => ({ ...m, id: nextId.current++ })))
      refreshState()
      refreshSummary() // 【阶段 5】之前生成过小结就显示出来
    } catch (e) {
      if (seq !== openSeq.current) return
      // 404：会话已经不在了（在别的窗口删了，或者是阶段 4 之前的旧会话，会话表里没有它）→ 当作新会话
      if (e.status === 404) newChat()
      else setMessages([{ id: nextId.current++, role: 'error', text: `加载聊天记录失败：${e.message}` }])
    } finally {
      if (seq === openSeq.current) setHistoryLoading(false)
    }
  }

  // 切换登录用户：加载这个用户的会话列表，打开他上次停留的会话（没有就是新会话）
  function switchUser(id) {
    userRef.current = id
    setUserId(id)
    writeStore(USER_KEY, id)
    setThreads([])
    refreshThreads()
    const saved = readStore(threadKey(id))
    if (saved) openThread(saved)
    else newChat()
  }

  // useEffect(函数, [])：组件第一次显示到页面上之后执行一次（[] = 不依赖任何状态，不重复执行）
  // 用来做「页面一打开就要做的事」：加载用户列表
  // 注意：开发模式下 StrictMode 会故意执行两次，所以会看到两个 /api/users 请求，打包上线后只有一次
  useEffect(() => {
    fetchUsers()
      .then((list) => {
        setUsers(list)
        const saved = readStore(USER_KEY)
        // 上次选过的用户还在列表里就用它，否则默认第一个
        const first = list.find((u) => u.user_id === saved) ?? list[0]
        if (first) switchUser(first.user_id)
      })
      .catch((e) => setLoadError(`加载用户失败：${e.message}。请确认后端已在 8001 端口启动。`))
  }, [])

  // 往消息列表末尾加一条。用 prev => [...prev, msg] 而不是 [...messages, msg]：
  // 连续两次 setMessages 时，messages 变量还是旧值，用 prev 才能保证拿到最新的列表
  function addMessage(msg) {
    const id = nextId.current++
    setMessages((prev) => [...prev, { id, ...msg }])
  }

  // 「新会话」按钮：丢掉当前 thread_id。下一句话不带 thread_id，后端就会开一段新对话
  // （旧对话还在后端，左侧会话列表里点它就能切回去 —— 阶段 4）
  function newChat() {
    openSeq.current++ // 正在加载的历史作废
    selectThread(null)
    setMessages([])
    setThreadState(null)
    resetSummary() // 【阶段 5】
    setHistoryLoading(false)
  }

  // 【阶段 4】删除会话：先弹窗确认（删了找不回来），删的是当前会话就切到新会话
  async function removeThread(id, title) {
    // window.confirm：浏览器自带的确认框，点「确定」返回 true。简单可靠，学习项目够用；
    //   真实产品一般换成自己画的弹窗（样式统一），逻辑一样：先确认，再调接口
    if (!window.confirm(`删除会话「${title}」？聊天记录和客服的记忆都会删掉，无法恢复。`)) return
    try {
      await deleteThread(userRef.current, id)
      if (id === threadRef.current) newChat()
    } catch (e) {
      window.alert(`删除失败：${e.message}`)
    }
    refreshThreads()
  }

  // 改某一条消息：用 id 找到它，交给 change 函数算出新的样子。
  // 为什么不直接改 m.text += ...：React 靠「对象换没换」判断要不要重画，原地修改对象页面不会更新，
  //   必须返回一个新对象（{ ...m, text: 新值 }），其他消息原样保留
  function updateMessage(id, change) {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...change(m) } : m)))
  }

  // 【阶段 2】把一条流式事件「应用」到客服消息 id 上：文字往后接、工具标签出现、参考资料补上……
  // 【阶段 3】从 send() 里抽出来：发新消息、审批后继续收到的是同一套事件，处理方式完全一样
  function applyEvent(id, event, data) {
    switch (event) {
      case 'run_started':
        // 新对话的 thread_id 一开始就拿到了，马上保存：就算中途出错，下一句也还接着这段对话
        // 【阶段 4】新会话已经在后端的会话表里了，刷新列表让它出现在左侧
        if (data.thread_id !== threadRef.current) {
          selectThread(data.thread_id)
          refreshThreads()
        }
        break
      case 'token':
        // call 变了 = 换了一次模型调用：上一段是「决定调工具前说的话」，不是最终回答，清空重新接
        updateMessage(id, (m) => ({
          text: data.call === m.call ? m.text + data.text : data.text,
          call: data.call,
        }))
        break
      case 'tool_started':
        // 工具开始：加一个「运行中」的标签；同时清掉之前那段铺垫文字（例如「我帮您查一下」）
        updateMessage(id, (m) => ({
          text: '',
          tools: [...m.tools, { id: data.id, name: data.name, args: data.args, status: 'running' }],
        }))
        break
      case 'tool_finished':
        // 工具结束：按 id 找到对应标签，改成完成 / 失败；知识库工具顺便带回参考资料
        updateMessage(id, (m) => ({
          tools: m.tools.map((t) => (t.id === data.id ? { ...t, status: data.ok ? 'ok' : 'error' } : t)),
          sources: [...m.sources, ...data.sources.filter((s) => !m.sources.includes(s))],
        }))
        break
      case 'tool_progress':
        // 【阶段 6】工具执行中的进度（目前只有检索知识库）：按 id 找到工具标签，同一个步骤只占一行 ——
        //   已经有这个 step 就替换（「向量检索中…」→「召回 10 条（0.62 秒）」），没有就加在后面。
        //   规则和后端 streaming/recorder.py 一样，刷新后从聊天记录读回来的进度和现在看到的一致
        updateMessage(id, (m) => ({
          tools: m.tools.map((t) => {
            if (t.id !== data.id) return t
            const item = { step: data.step, status: data.status, message: data.message }
            const old = t.progress ?? []
            const has = old.some((p) => p.step === data.step)
            return { ...t, progress: has ? old.map((p) => (p.step === data.step ? item : p)) : [...old, item] }
          }),
        }))
        break
      case 'approval_required':
        updateMessage(id, () => ({ pending: data.pending }))
        break
      case 'error':
        updateMessage(id, () => ({ error: data.message }))
        break
      case 'done':
        // 正常结束 / 停在审批上：以后端的完整结果为准（return_direct 的工具结果只在这里才有）
        if (data.status !== 'error') {
          updateMessage(id, () => ({ text: data.answer, sources: data.sources, pending: data.pending_approvals }))
        }
        break
      default:
      // 不认识的事件直接忽略：以后后端加了新事件（例如阶段 6 的检索进度），旧页面也不会出错
    }
  }

  // 【阶段 3】跑一次流式请求，结果写进客服消息 id。
  //   start(signal, onEvent)：真正发请求的函数 —— 发新消息传 streamChat，审批后继续传 resumeChat，其余步骤完全一样
  // async：函数里要 await（等待）整个流读完
  async function runStream(id, start) {
    // AbortController：浏览器自带的「中止器」。controller.signal 交给 fetch，之后 controller.abort() 就能中断这次请求
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    try {
      await start(controller.signal, (event, data) => applyEvent(id, event, data))
    } catch (e) {
      if (e.name === 'AbortError') {
        // 点了「停止」：已经显示的文字保留（和 ChatGPT 一样），还在转圈的工具标签改成「已停止」
        updateMessage(id, (m) => ({
          stopped: true,
          tools: m.tools.map((t) => (t.status === 'running' ? { ...t, status: 'stopped' } : t)),
        }))
      } else {
        // 还没开始推流就失败（401 / 403 / 409 / 后端没启动）：
        //   消息还是空的 → 整条换成红色错误提示；已经有内容（例如审批后继续失败）→ 保留内容，下面加一条错误
        updateMessage(id, (m) =>
          m.text || m.tools.length > 0 || m.decision ? { error: e.message } : { role: 'error', text: e.message },
        )
      }
    } finally {
      // finally：成功、失败、停止都会执行 —— 保证不会一直显示「正在输入」
      abortRef.current = null
      updateMessage(id, () => ({ streaming: false }))
      setLoading(false)
      // 【阶段 4】这一轮结束（不管怎么结束的）：会话排到列表最上面，侧边栏的 State 更新
      refreshThreads()
      refreshState()
      refreshSummary() // 【阶段 5】有新消息了，已有的小结会变成「过期」
    }
  }

  // 【阶段 2】发送一句话：先放上用户的话，再放一条空的客服消息（streaming: true，页面显示「正在输入」），然后开始收流
  async function send(text) {
    addMessage({ role: 'user', text })
    const id = nextId.current++ // 先拿到客服消息的 id，后面的事件都按这个 id 去改它
    setMessages((prev) => [
      ...prev,
      { id, role: 'assistant', text: '', call: 0, tools: [], sources: [], pending: [], streaming: true },
    ])
    await runStream(id, (signal, onEvent) => streamChat(userId, threadRef.current, text, onEvent, signal))
  }

  // 【阶段 3】审批卡片上点了「批准 / 拒绝」：在同一条客服消息里接着显示后面的过程
  //   ① 卡片换成一条「已批准 / 已拒绝」的记录（decision），pending 清空，按钮就消失了，不会被点第二次
  //   ② text 清空、call 归零：后端这次是一轮新的运行，模型调用次数从 1 重新数，最终回答以这次为准
  // useCallback：让这个函数在每次重画之间保持「同一个函数」（什么时候才换新函数，看最后的依赖列表）。
  //   它要作为 props 传给每一条 MessageBubble；如果每次重画都是新函数，memo 会认为 props 变了，流式时所有消息又会每个字重画一次
  const decide = useCallback(
    async (id, approved, reason) => {
      updateMessage(id, (m) => ({
        decision: { approved, reason, items: m.pending },
        pending: [],
        text: '',
        call: 0,
        error: undefined,
        streaming: true,
      }))
      // 【阶段 4】threadRef.current 而不是 threadId：理由见 threadRef 的注释
      await runStream(id, (signal, onEvent) => resumeChat(userRef.current, threadRef.current, approved, reason, onEvent, signal))
    },
    // 【阶段 4】用户和会话都从 ref 读，里面用到的 runStream 也只用 setXxx 和 ref，不依赖任何 state，
    //   所以依赖列表是 [] = 永远是同一个函数，MessageBubble 一次都不会因为它重画
    [],
  )

  // 【阶段 3】「停止」按钮：中断当前请求（?.：没有正在进行的请求时什么也不做）
  function stop() {
    abortRef.current?.abort()
  }

  const currentUser = users.find((u) => u.user_id === userId)

  // 页面结构：左边 Sidebar（品牌、新会话、切换用户、会话信息），右边 顶栏 + ChatWindow
  return (
    <div className="app">
      <Sidebar
        users={users}
        userId={userId}
        threadId={threadId}
        threads={threads}
        threadState={threadState}
        loading={loading}
        open={sidebarOpen}
        // 窄屏下选完用户 / 点完新会话，顺手收起侧边栏
        onSwitchUser={(id) => {
          switchUser(id)
          setSidebarOpen(false)
        }}
        onNewChat={() => {
          newChat()
          setSidebarOpen(false)
        }}
        onOpenThread={(id) => {
          if (id !== threadId) openThread(id)
          setSidebarOpen(false)
        }}
        onDeleteThread={removeThread}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="main">
        <header className="topbar">
          {/* 菜单按钮：只在窄屏（手机）显示，点开侧边栏（CSS 里 @media 控制显示与否） */}
          <button className="menu-btn" onClick={() => setSidebarOpen(true)} aria-label="打开菜单">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          {/* 【阶段 4】顶栏标题 = 会话列表里的标题（第一句话） */}
          <div className="topbar-title">{threads.find((t) => t.thread_id === threadId)?.title ?? '新对话'}</div>
          {/* 【阶段 5】小结、消息链都针对「当前会话」，还没开始聊（没有 threadId）时不能点；
              回答过程中也不能生成小结：这时 checkpointer 里的对话还没完整 */}
          <div className="topbar-actions">
            <button className="top-btn" onClick={makeSummary} disabled={!threadId || loading || summaryBusy}>
              {summaryBusy ? '生成中…' : summary ? '重新生成小结' : '生成小结'}
            </button>
            <button className="top-btn" onClick={() => setChainOpen(true)} disabled={!threadId}>
              消息链
            </button>
          </div>
          {currentUser && (
            <div className="topbar-user">
              <span className={`avatar small ${currentUser.role}`}>{currentUser.name.slice(0, 1)}</span>
              {currentUser.name}
            </div>
          )}
        </header>

        {loadError && <div className="banner-error">{loadError}</div>}

        {/* 【阶段 5】小结卡片：有小结、正在生成、或者出错时显示 */}
        {!summaryHidden && (
          <SummaryCard
            data={summary}
            busy={summaryBusy}
            error={summaryError}
            onRegenerate={makeSummary}
            onClose={() => setSummaryHidden(true)}
          />
        )}

        <ChatWindow
          messages={messages}
          loading={loading}
          disabled={!currentUser}
          userName={currentUser?.name}
          historyLoading={historyLoading}
          onSend={send}
          onStop={stop}
          onDecide={decide}
        />
      </div>

      {/* 【阶段 5】消息链面板（从右侧滑出，盖在聊天区上面） */}
      <ChainPanel open={chainOpen} userId={userId} threadId={threadId} onClose={() => setChainOpen(false)} />
    </div>
  )
}

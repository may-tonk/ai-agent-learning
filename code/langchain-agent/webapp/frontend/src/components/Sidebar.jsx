// 【v2 网页版新增】左侧边栏：品牌、新会话按钮、历史会话列表（阶段 4）、切换登录用户、当前会话信息
//
// 【在整体流程里的位置】App.jsx 把用户列表、会话列表、当前会话的 State 通过 props 传进来；
//   点「新会话」、某个会话、某个用户、垃圾桶时，调用 App 传进来的 onXxx 函数 —— 本组件只管显示，不保存任何状态。
// 和命令行 main.py 的对应：choose_user() → 用户列表；/new 命令 → 「新会话」按钮；/state 命令 → 底部「当前会话」卡片
import { ROLE_LABELS } from '../constants.js'

// 【阶段 4】会话的时间显示：今天的只显示「16:30」，更早的显示「10-28」
//   updated_at 是后端存的「2026-10-29T16:30:05」这种字符串，直接截取，不用引入日期库
function shortTime(iso) {
  const today = new Date().toLocaleDateString('sv') // 'sv'（瑞典）地区的格式正好是 2026-10-29，和后端一致
  return iso.slice(0, 10) === today ? iso.slice(11, 16) : iso.slice(5, 10)
}

/**
 * props：
 *   users         用户列表 [{user_id, name, role}]
 *   userId        当前登录用户 ID
 *   threadId      当前会话 ID（null = 还没开始）
 *   threads       【阶段 4】会话列表 [{thread_id, title, updated_at}]
 *   threadState   【阶段 4】当前会话的 State {current_order_id, token_usage, memory_messages}（null = 还没有）
 *   loading       是否在等回答（等待时不允许切用户、开新会话，避免回答回来时串到别的会话）
 *   open          手机窄屏时侧边栏是否展开（宽屏一直显示，不看这个值）
 *   onSwitchUser  点某个用户时调用，参数是 user_id
 *   onNewChat     点「新会话」时调用
 *   onOpenThread  【阶段 4】点某个会话时调用，参数是 thread_id
 *   onDeleteThread【阶段 4】点会话旁边的垃圾桶时调用，参数是 (thread_id, 标题)
 *   onClose       窄屏下点遮罩时调用，收起侧边栏
 */
export default function Sidebar({
  users,
  userId,
  threadId,
  threads,
  threadState,
  loading,
  open,
  onSwitchUser,
  onNewChat,
  onOpenThread,
  onDeleteThread,
  onClose,
}) {
  const usage = threadState?.token_usage // ?.：threadState 是 null 时整个表达式就是 undefined，不会报错
  return (
    <>
      {/* 遮罩：只在窄屏且侧边栏展开时由 CSS 显示，点它收起侧边栏 */}
      <div className={`scrim ${open ? 'show' : ''}`} onClick={onClose} />

      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-logo" aria-hidden="true">
            {/* 内联 SVG 图标：不依赖图片文件和图标库，颜色跟随 CSS 的 currentColor */}
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="8.5" />
              <circle cx="12" cy="12" r="3" />
              <path d="M12 3.5v3M7 6.5l1.5 2M17 6.5l-1.5 2" strokeLinecap="round" />
            </svg>
          </div>
          <div>
            <div className="brand-name">智扫通</div>
            <div className="brand-sub">售后智能客服</div>
          </div>
        </div>

        <button className="new-chat" onClick={onNewChat} disabled={loading || !userId}>
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          新会话
        </button>

        {/* 【阶段 4】历史会话：占满中间剩下的高度，会话多了在这一块里滚动（CSS .thread-section） */}
        <div className="side-section thread-section">
          <div className="side-label">历史会话</div>
          {threads.length === 0 && <div className="thread-empty">还没有会话，发第一句话后会出现在这里</div>}
          <div className="thread-list">
            {threads.map((t) => (
              // 一行里有两个按钮（打开、删除）。不能把删除按钮放进打开按钮里面：HTML 不允许按钮套按钮
              <div key={t.thread_id} className={`thread-item ${t.thread_id === threadId ? 'active' : ''}`}>
                <button
                  className="thread-open"
                  onClick={() => onOpenThread(t.thread_id)}
                  disabled={loading}
                  title={t.title}
                >
                  <span className="thread-title">{t.title}</span>
                  <span className="thread-time">{shortTime(t.updated_at)}</span>
                </button>
                <button
                  className="thread-delete"
                  onClick={() => onDeleteThread(t.thread_id, t.title)}
                  disabled={loading}
                  aria-label={`删除会话 ${t.title}`}
                  title="删除会话"
                >
                  {/* 垃圾桶图标 */}
                  <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
                    <path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 12.5h9l1-12.5M10 11v5M14 11v5" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        </div>

        <div className="side-section">
          <div className="side-label">切换登录用户</div>
          {users.map((u) => (
            // 用 <button> 而不是 <div onClick>：键盘 Tab 能选中、屏幕阅读器能识别，是正规做法
            <button
              key={u.user_id}
              className={`user-item ${u.user_id === userId ? 'active' : ''}`}
              onClick={() => onSwitchUser(u.user_id)}
              disabled={loading}
            >
              {/* 头像：取名字的第一个字。role 不同头像颜色不同（CSS 里 .avatar.supervisor） */}
              <span className={`avatar ${u.role}`}>{u.name.slice(0, 1)}</span>
              <span className="user-meta">
                <span className="user-name">{u.name}</span>
                <span className="user-id">{u.user_id}</span>
              </span>
              <span className={`role-badge ${u.role}`}>{ROLE_LABELS[u.role] ?? u.role}</span>
            </button>
          ))}
        </div>

        {/* margin-top: auto（见 CSS）：把这一块推到侧边栏最底部 */}
        <div className="session-card">
          <div className="side-label">当前会话</div>
          <div className="session-row">
            <span>会话 ID</span>
            {/* title：鼠标悬停显示完整 ID（框太窄时会被截断显示省略号） */}
            <code title={threadId ?? ''}>{threadId ?? '发送第一句话后生成'}</code>
          </div>
          <div className="session-row">
            <span>累计 token</span>
            <b>{usage ? usage.total_tokens.toLocaleString() : '—'}</b>
          </div>
          <div className="session-row">
            <span>模型调用</span>
            <b>{usage ? `${usage.model_calls} 次` : '—'}</b>
          </div>
          {/* 【阶段 4】下面两行来自 checkpointer 存档里的 State（GET /api/threads/{id}/state） */}
          <div className="session-row">
            <span>当前订单</span>
            <b>{threadState?.current_order_id ?? '—'}</b>
          </div>
          <div className="session-row">
            {/* 模型下次被调用时会带上的历史条数。对话很长被摘要压缩后，会比页面上的气泡少 */}
            <span title="存档里的消息条数：下次调用模型时带上的历史">记忆中的消息</span>
            <b>{threadState ? `${threadState.memory_messages} 条` : '—'}</b>
          </div>
        </div>
      </aside>
    </>
  )
}

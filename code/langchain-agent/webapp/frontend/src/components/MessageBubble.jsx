// 【v2 网页版新增】一条消息的样子：用户的话、客服的回答（带工具调用、参考资料、待审批）、错误提示
//
// 【阶段 2】客服消息是「边收边长」的：streaming 为 true 时，
//   还没有文字 → 显示三个跳动的点；已经有文字 → 文字末尾显示一个闪烁的光标
//   工具标签有三种状态：running（转圈）→ ok（打勾）/ error（红叉），由 tool_started / tool_finished 事件驱动
//
// 【阶段 3】
//   待审批卡片有了「批准执行 / 拒绝」按钮（ApprovalCard），点了调用 App 的 decide()；做完决定后卡片变成一条记录（decision）
//   点了「停止」：消息带 stopped，显示「已停止生成」，没跑完的工具标签是 stopped 状态（灰色叉）
//
// 【阶段 6】工具标签下面多了「进度」：检索知识库时一步步显示「向量检索中… → 召回 10 条（0.62 秒）→ 重排后保留 3 条」
//   数据来自 tool_progress 事件（App.jsx 的 applyEvent 把它放进 tool.progress），刷新后从聊天记录里读回来
//
// 对应命令行 main.py 的 render()：
//   「[调用工具] 名字 参数」 → 回答上方的「步骤」小标签（显示中文名，鼠标悬停看参数）
//   回答正文                 → 用 Markdown 渲染（模型爱输出 **加粗**、列表、表格，原样显示很难看）
//   「参考资料：…」          → 回答下方的文件小卡片
//   「【需要客服审批】」+ 输入 y/n → 黄色审批卡片 + 「批准执行 / 拒绝」按钮（阶段 3）
//
// 新依赖（本次 npm install 装的）：
//   react-markdown：把 Markdown 文字变成 React 元素。它不用 innerHTML，模型输出里就算夹着 <script> 也不会被执行，安全
//   remark-gfm：react-markdown 的插件，支持 GitHub 风格的扩展语法：表格、删除线、任务列表
import { memo, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { TOOL_LABELS } from '../constants.js'

// 客服头像：一个圆形里画扫地机器人图标。单独写成小组件，「正在输入」那一行也要用它
export function BotAvatar() {
  return (
    <div className="bot-avatar" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8">
        <circle cx="12" cy="12" r="8.5" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </div>
  )
}

// 工具标签前面的小图标：运行中转圈、成功打勾、失败打叉
function StepIcon({ status }) {
  if (status === 'running') return <span className="spinner" aria-hidden="true" />
  // error（失败）和 stopped（停止了）都画叉，颜色由 CSS 的 .step.error / .step.stopped 区分
  const d = status === 'ok' ? 'M5 12.5l4.5 4.5L19 7.5' : 'M7 7l10 10M17 7L7 17'
  return (
    <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  )
}

// 【阶段 3】审批卡片：列出待审批的操作 + 「批准执行 / 拒绝」按钮。
//   点「拒绝」不会马上发请求，先展开一个理由输入框（理由会作为工具结果交给模型，模型据此回复用户），再点「确认拒绝」才发
//   props：pending 待审批操作列表；busy 是否有请求正在进行（这时按钮禁用）；onDecide(approved, reason) 做出决定
function ApprovalCard({ pending, busy, onDecide }) {
  // 这两个状态只和这张卡片有关，放在卡片自己里面，App 不用管（「状态放在用到它的最近的组件里」是 React 的常见做法）
  const [rejecting, setRejecting] = useState(false) // 是否展开了「拒绝理由」输入框
  const [reason, setReason] = useState('')

  return (
    <div className="pending-card">
      <b>以下操作需要审批后才会执行</b>
      {pending.map((p, i) => (
        <div key={i} className="pending-item">
          <span>{TOOL_LABELS[p.name] ?? p.name}</span>
          <code>{JSON.stringify(p.args)}</code>
        </div>
      ))}
      {rejecting ? (
        <div className="approval-actions">
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="拒绝理由（可不填）"
            maxLength={200} // 和后端 ResumeRequest.reason 的 max_length 一致
            autoFocus
          />
          <button className="btn danger" disabled={busy} onClick={() => onDecide(false, reason.trim())}>
            确认拒绝
          </button>
          <button className="btn ghost" disabled={busy} onClick={() => setRejecting(false)}>
            取消
          </button>
        </div>
      ) : (
        <div className="approval-actions">
          <button className="btn primary" disabled={busy} onClick={() => onDecide(true, '')}>
            批准执行
          </button>
          <button className="btn ghost" disabled={busy} onClick={() => setRejecting(true)}>
            拒绝
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * props：
 *   message   {id, role: 'user' | 'assistant' | 'error', text, tools?, sources?, pending?, decision?, error?, streaming?, stopped?}
 *             tools：[{id, name, args, status: 'running' | 'ok' | 'error' | 'stopped'}]
 *             decision：{approved, reason, items}（阶段 3：审批卡片点过之后的记录）
 *   busy      是否有请求正在进行（审批按钮要禁用）
 *   onDecide  审批回调：onDecide(消息 id, approved, reason)，来自 App 的 decide()
 */
function MessageBubble({ message, busy, onDecide }) {
  const { role, text, tools = [], sources = [], pending = [], decision, error, streaming, stopped } = message

  // ① 用户的话：靠右的彩色气泡，纯文字（用户输入不当 Markdown 解析，输入什么就显示什么）
  if (role === 'user') {
    return (
      <div className="row user">
        <div className="bubble-user">{text}</div>
      </div>
    )
  }

  // ② 错误：靠左的红色提示卡（后端 401 / 403 / 409 / 5xx 返回的 detail）
  if (role === 'error') {
    return (
      <div className="row assistant">
        <div className="error-card">
          <b>出错了</b>
          <span>{text}</span>
        </div>
      </div>
    )
  }

  // ③ 客服回答：左边头像，右边依次是「调用了哪些工具」→ 正文 → 待审批 → 参考资料
  return (
    <div className="row assistant">
      <BotAvatar />
      <div className="answer">
        {tools.length > 0 && (
          <div className="steps">
            {tools.map((t) => (
              // key 用 tool_call_id：每次工具调用唯一，比用下标稳定
              // title：鼠标悬停显示原始工具名和参数，方便调试时核对模型传了什么
              <span key={t.id} className={`step ${t.status}`} title={`${t.name} ${JSON.stringify(t.args)}`}>
                <StepIcon status={t.status} />
                {/* ?? ：左边是 undefined（没登记的新工具）时用右边的英文名 */}
                {TOOL_LABELS[t.name] ?? t.name}
                {t.status === 'running' && '中…'}
                {t.status === 'stopped' && '（已停止）'}
              </span>
            ))}
          </div>
        )}

        {/* 【阶段 6】工具进度：每个有进度的工具一行，步骤之间用箭头连起来；正在进行的那一步带转圈 */}
        {tools
          .filter((t) => t.progress?.length)
          .map((t) => (
            <div key={t.id} className="tool-progress">
              <span className="tool-progress-name">{TOOL_LABELS[t.name] ?? t.name}</span>
              {t.progress.map((p, i) => (
                <span key={p.step} className={`progress-step ${p.status}`}>
                  {i > 0 && <span className="progress-arrow">→</span>}
                  {/* 工具已经结束（ok / error / stopped）就不再转圈，哪怕最后一步没收到 done */}
                  {p.status === 'running' && t.status === 'running' && <span className="spinner" aria-hidden="true" />}
                  {p.message}
                </span>
              ))}
            </div>
          ))}

        {/* 还在等、一个字都没有：三个跳动的点（动画在 CSS 的 @keyframes blink） */}
        {streaming && !text && !error && (
          <div className="typing">
            <span />
            <span />
            <span />
          </div>
        )}

        {/* 正文用 Markdown 渲染。停在审批上时回答可能是空的，就不显示这一块 */}
        {/* streaming 时加 class="streaming"：CSS 在最后一个段落末尾画一个闪烁的光标 */}
        {text && (
          <div className={`markdown ${streaming ? 'streaming' : ''}`}>
            <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
          </div>
        )}

        {/* 推流过程中出错（模型超时、限流…）：已经显示的文字保留，下面加一条红色提示 */}
        {error && (
          <div className="error-card">
            <b>出错了</b>
            <span>{error}</span>
          </div>
        )}

        {pending.length > 0 && (
          // 把消息 id 补上再交给 App：卡片自己不知道自己属于哪条消息
          <ApprovalCard pending={pending} busy={busy} onDecide={(approved, reason) => onDecide(message.id, approved, reason)} />
        )}

        {/* 【阶段 3】审批过的记录：卡片点过之后换成这一行，按钮消失，避免重复提交 */}
        {decision && (
          <div className={`decision ${decision.approved ? 'approved' : 'rejected'}`}>
            {decision.approved ? '已批准' : '已拒绝'}：{decision.items.map((p) => TOOL_LABELS[p.name] ?? p.name).join('、')}
            {decision.reason && `（理由：${decision.reason}）`}
          </div>
        )}

        {/* 【阶段 3】点了「停止」：已经生成的文字保留，下面标一行 */}
        {stopped && <div className="stopped-note">已停止生成</div>}

        {sources.length > 0 && (
          <div className="sources">
            <span className="sources-label">参考资料</span>
            {sources.map((s) => (
              <span key={s} className="source-chip" title={s}>
                <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" />
                  <path d="M14 3v5h5" />
                </svg>
                {/* 后端给的可能是带目录的路径，只显示最后的文件名，完整路径放在 title 里 */}
                {s.split(/[\\/]/).pop()}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// memo：props 没变就不重画。流式时每来一个字，App 都会生成新的 messages 列表，
//   但只有正在生成的那条消息对象是新的，其他消息对象没变 —— 有了 memo，它们的 Markdown 不用每个字都重新解析一遍
export default memo(MessageBubble)

// 【v2 网页版新增】对话区域：欢迎页（还没聊天时）或消息列表，下面是输入框和发送按钮
//
// 【在整体流程里的位置】App.jsx 把 messages、loading 等数据通过 props 传进来；
//   用户点发送（或点欢迎页的示例问题）时，调用 App 传进来的 onSend(text)，真正发请求的是 App —— 本组件只管「显示」和「收集输入」。
// 为什么这样分：数据和请求集中在 App 一处管理；ChatWindow 不知道后端存在，阶段 2 换成流式后，它确实只改了「正在输入」的位置。
import { useEffect, useRef, useState } from 'react'
import MessageBubble, { BotAvatar } from './MessageBubble.jsx'
import { SUGGESTIONS } from '../constants.js'

/**
 * props（父组件传进来的参数）：
 *   messages  要显示的消息列表
 *   loading   是否在等后端回答
 *   disabled  是否禁用输入（还没选好用户时）
 *   userName  当前用户名字，欢迎语里用
 *   historyLoading 【阶段 4】是否正在加载聊天记录（打开会话、刷新页面时）
 *   onSend    发送函数，参数是输入的文字
 *   onStop    【阶段 3】停止生成（App 的 stop）
 *   onDecide  【阶段 3】审批卡片的回调（App 的 decide），原样转交给每一条 MessageBubble
 */
export default function ChatWindow({ messages, loading, disabled, userName, historyLoading, onSend, onStop, onDecide }) {
  const [input, setInput] = useState('') // 输入框里当前的文字
  const bottomRef = useRef(null) // 指向列表最底部的一个空 div，用来自动滚动
  const textareaRef = useRef(null) // 指向输入框，用来按内容调整高度、发送后重新聚焦

  // 每次消息变化（新消息、流式时每来一个字）时，滚动到最底部，让最新的内容可见
  // [messages, loading]：只有这两个值变化时才执行
  // 【阶段 2】生成中用 'auto'（立刻跳到底）：每秒几十个字，每次都用 'smooth' 慢慢滚，动画会互相打断、画面发抖
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: loading ? 'auto' : 'smooth' })
  }, [messages, loading])

  // 输入框自动长高：先把高度清成 auto，再设成内容实际需要的高度（scrollHeight），最高 200px（之后出滚动条，见 CSS max-height）
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [input])

  // 发送：输入框的发送和示例问题共用这一个函数
  function sendText(raw) {
    const text = raw.trim()
    if (!text || loading || disabled) return // 空消息、正在等回答时不发
    onSend(text)
    setInput('')
    textareaRef.current?.focus() // 发完光标留在输入框，可以接着打字
  }

  function submit(e) {
    e.preventDefault() // 阻止表单默认行为（默认会刷新整个页面）
    sendText(input)
  }

  // Enter 发送，Shift+Enter 换行（聊天软件的通用习惯）
  // isComposing：正在用中文输入法选字时按的 Enter 是「确认选字」，不能当成发送
  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) submit(e)
  }

  const empty = messages.length === 0

  return (
    <main className="chat">
      <div className="messages">
        <div className="column">
          {/* 欢迎页：还没有消息、也不是在加载聊天记录时显示 */}
          {empty && !historyLoading && (
            <div className="welcome">
              <div className="welcome-logo">
                <BotAvatar />
              </div>
              <h2>{userName ? `${userName}，你好` : '你好'}，我是智扫通售后客服</h2>
              <p>可以问我产品使用、订单查询、保修判断和报修的问题。</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s.title} className="suggestion" onClick={() => sendText(s.text)} disabled={loading || disabled}>
                    <b>{s.title}</b>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* 【阶段 4】打开会话后，聊天记录还没从后端拿回来时的提示（通常一闪而过） */}
          {empty && historyLoading && <div className="notice">正在加载聊天记录…</div>}

          {/* key：React 用它区分列表里的每一项，必须唯一且稳定（这里用 App 里生成的编号） */}
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} busy={loading} onDecide={onDecide} />
          ))}

          {/* 【阶段 2】「正在输入」的三个点挪进了 MessageBubble：客服消息一开始是空的，边收边长 */}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="composer-wrap">
        <form className="composer" onSubmit={submit}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="输入你的问题…"
            rows={1}
            maxLength={2000} // 和后端 ChatRequest 的 max_length 一致：前端先拦一次，体验更好；后端还会再校验
            disabled={disabled}
          />
          {/* 【阶段 3】生成中：发送按钮换成「停止」按钮（方块图标，和 ChatGPT 一样）
              type="button"：不是提交按钮，点它不会触发表单的 onSubmit
              key 不同：让 React 把它们当成两个按钮，换的时候直接换掉，而不是改同一个按钮的 class
                （改 class 会触发 .send 的背景色过渡动画，实测截图里能看到按钮从黑色慢慢变灰） */}
          {loading ? (
            <button key="stop" type="button" className="send stop" onClick={onStop} aria-label="停止生成" title="停止生成">
              <svg viewBox="0 0 24 24" width="14" height="14">
                <rect x="5" y="5" width="14" height="14" rx="2.5" fill="currentColor" />
              </svg>
            </button>
          ) : (
            <button key="send" type="submit" className="send" disabled={disabled || !input.trim()} aria-label="发送">
              <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 19V5M5 12l7-7 7 7" />
              </svg>
            </button>
          )}
        </form>
        <div className="hint">Enter 发送 · Shift + Enter 换行 · 生成中可点方块停止 · 回答由 AI 生成，请以实际售后政策为准</div>
      </div>
    </main>
  )
}

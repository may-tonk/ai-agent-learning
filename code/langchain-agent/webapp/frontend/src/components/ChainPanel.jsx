// 【v2 网页版新增 · 阶段 5】「消息链」调试面板：从右侧滑出，显示 checkpointer 里的原始消息（对应命令行版 /history）
//
// 【为什么要有它】页面上的一个客服气泡，在模型的记忆里其实是好几条消息：
//   human（用户的话）→ ai（请求调用工具，带 tool_calls）→ tool（工具结果，带 tool_call_id）→ ai（最终回答）
//   这个面板把它们原样列出来，并且把 tool_calls[].id 和 tool_call_id 用同一种颜色标出 ——
//   模型就是靠这个 ID 知道「哪个结果回答的是哪个请求」（同一轮调用多个工具时尤其重要）。
// 【在整体流程里的位置】顶栏点「消息链」→ 本组件打开时 GET /api/threads/{id}/chain → 列出来；点「刷新」再读一次
// 这是给开发者学习、排查问题用的，真实产品里一般只对管理员开放
import { useEffect, useState } from 'react'
import { fetchChain } from '../api/client.js'

// 消息类型 → 显示的中文名
const TYPE_LABELS = { human: '用户 human', ai: '模型 ai', tool: '工具 tool', system: '系统 system' }
// 给 tool_call_id 配色用的几种颜色（同一个 ID 两处颜色一样，就能一眼看出配对）
const ID_COLORS = ['#0e9384', '#7c3aed', '#c2410c', '#2563eb', '#be185d', '#4d7c0f']

/**
 * props：
 *   open      是否显示
 *   userId    当前用户（请求头）
 *   threadId  当前会话
 *   onClose   点 × 或遮罩时调用
 */
export default function ChainPanel({ open, userId, threadId, onClose }) {
  const [chain, setChain] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function load() {
    if (!threadId) return
    setLoading(true)
    setError('')
    fetchChain(userId, threadId)
      .then(setChain)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }

  // 面板打开、或者打开状态下换了会话 → 重新读
  useEffect(() => {
    if (open) load()
  }, [open, threadId])

  // 按出现顺序给每个工具调用 ID 分配一种颜色
  const colorOf = {}
  chain.forEach((m) =>
    m.tool_calls.forEach((c) => {
      colorOf[c.id] ??= ID_COLORS[Object.keys(colorOf).length % ID_COLORS.length]
    }),
  )

  if (!open) return null
  return (
    <>
      <div className="chain-scrim" onClick={onClose} />
      <aside className="chain-panel">
        <div className="chain-head">
          <div>
            <div className="chain-title">消息链</div>
            <div className="chain-sub">checkpointer 里的原始消息（模型下次会看到的上下文），共 {chain.length} 条</div>
          </div>
          <button className="btn" onClick={load} disabled={loading}>{loading ? '读取中…' : '刷新'}</button>
          <button className="summary-close" onClick={onClose} aria-label="关闭">×</button>
        </div>
        {error && <div className="summary-error">{error}</div>}
        <ol className="chain-list">
          {chain.map((m) => (
            <li key={m.index} className={`chain-item chain-${m.type}`}>
              <div className="chain-meta">
                <span className="chain-index">#{m.index}</span>
                <span className="chain-type">{m.is_summary ? '摘要（SummarizationMiddleware 压缩的旧对话）' : TYPE_LABELS[m.type] ?? m.type}</span>
                {m.tool_name && <span className="chain-toolname">{m.tool_name}</span>}
                {m.status === 'error' && <span className="tag tag-warn">error</span>}
              </div>
              {/* ai 消息：请求调用的工具，每个带一个 id */}
              {m.tool_calls.map((c) => (
                <div key={c.id} className="chain-call">
                  调用 <b>{c.name}</b>({JSON.stringify(c.args)})
                  <code style={{ color: colorOf[c.id] }}>id = {c.id}</code>
                </div>
              ))}
              {/* tool 消息：回答的是哪个 id */}
              {m.tool_call_id && (
                <div className="chain-call">
                  回答 <code style={{ color: colorOf[m.tool_call_id] }}>tool_call_id = {m.tool_call_id}</code>
                </div>
              )}
              {m.text && (
                <div className="chain-text">
                  {m.text}
                  {m.length > m.text.length && <span className="chain-more">…（共 {m.length} 字）</span>}
                </div>
              )}
            </li>
          ))}
        </ol>
      </aside>
    </>
  )
}

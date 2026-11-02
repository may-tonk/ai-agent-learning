// 【v2 网页版新增 · 阶段 5】会话小结卡片：顶栏下面、聊天区上面，显示「生成小结」的结果
//
// 【在整体流程里的位置】顶栏点「生成小结」→ App.makeSummary() → POST /api/threads/{id}/summary
//   → 后端用结构化输出让 DeepSeek 填好 ServiceSummary 的 7 个字段 → 存进小结表 → 返回 → 本组件显示
//   打开会话时 App 也会读一次（GET），之前生成过的小结直接显示，不用重新生成
// 和命令行 main.py 的对应：/summary 命令打印的那段 JSON → 这里换成一张能看懂的卡片
import { useState } from 'react'

// 满意度风险 → 颜色：高 = 红，中 = 橙，低 = 绿（复用 styles.css 里已有的颜色变量）
const RISK_CLASS = { 高: 'risk-high', 中: 'risk-mid', 低: 'risk-low' }

/**
 * props：
 *   data        小结 {summary, created_at, message_count, stale}；null = 还没有
 *   busy        是否正在生成（按钮显示「生成中…」，不能重复点）
 *   error       生成失败的提示（为空 = 没出错）
 *   onRegenerate 点「重新生成」时调用
 *   onClose      点 × 时调用（只是收起卡片，小结还在数据库里）
 */
export default function SummaryCard({ data, busy, error, onRegenerate, onClose }) {
  // 卡片可以折叠成一行：小结字段多，聊天时不想让它一直占地方
  const [collapsed, setCollapsed] = useState(false)
  if (!data && !busy && !error) return null // 什么都没有就不显示

  const s = data?.summary
  return (
    <section className="summary-card">
      <div className="summary-head">
        <button className="summary-toggle" onClick={() => setCollapsed(!collapsed)} aria-expanded={!collapsed}>
          <span className={`chevron ${collapsed ? '' : 'down'}`}>›</span>
          会话小结
        </button>
        {/* 一行里能看到最关键的三样：分类、是否解决、满意度风险 */}
        {s && (
          <div className="summary-tags">
            <span className="tag">{s.category}</span>
            <span className={`tag ${s.resolved ? 'tag-ok' : 'tag-warn'}`}>{s.resolved ? '已解决' : '未解决'}</span>
            <span className={`tag ${RISK_CLASS[s.satisfaction_risk]}`}>满意度风险：{s.satisfaction_risk}</span>
          </div>
        )}
        <button className="summary-close" onClick={onClose} aria-label="收起小结">×</button>
      </div>

      {!collapsed && (
        <div className="summary-body">
          {busy && <div className="summary-note">正在生成小结（调用一次 DeepSeek，几秒钟）…</div>}
          {error && <div className="summary-error">{error}</div>}
          {/* 过期提示：生成之后又聊过，小结只代表之前的对话（后端比较消息条数得出） */}
          {data?.stale && !busy && (
            <div className="summary-stale">
              生成之后又有了新消息，这份小结可能不完整。
              <button className="link-btn" onClick={onRegenerate}>重新生成</button>
            </div>
          )}
          {s && (
            <dl className="summary-grid">
              <dt>用户诉求</dt>
              <dd>{s.user_intent}</dd>
              <dt>相关订单</dt>
              <dd>{s.related_orders.length ? s.related_orders.join('、') : '无'}</dd>
              <dt>工单号</dt>
              <dd>{s.ticket_ids.length ? s.ticket_ids.join('、') : '无'}</dd>
              <dt>后续跟进</dt>
              <dd>{s.follow_up || '无'}</dd>
            </dl>
          )}
          {data && <div className="summary-meta">生成于 {data.created_at.replace('T', ' ')}，基于前 {data.message_count} 条消息</div>}
        </div>
      )}
    </section>
  )
}

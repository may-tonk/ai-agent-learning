// 【v2 网页版新增】调用后端接口的函数：页面组件只调用这里，不直接写 fetch
//
// 为什么单独放一个文件（真实项目的做法）：
//   ① 请求头（X-User-Id）、错误处理只写一处，所有接口共用
//   ② 以后接口地址、登录方式（换成 JWT）变了，只改这个文件，组件不用动
//   ③ 阶段 2 的流式接口放在旁边的 sse.js，和这里的「普通请求」分开
// 谁调用：src/App.jsx

/**
 * 发一个 JSON 请求，返回解析好的 JSON。
 * @param {string} path    接口路径，例如 '/api/chat'（Vite 会转发给 :8001 的后端）
 * @param {object} options
 *   method  'GET' / 'POST'，默认 GET
 *   body    要发送的数据（普通 JS 对象，这里负责转成 JSON 字符串）
 *   userId  当前登录用户，放进 X-User-Id 请求头（后端 deps.get_current_user 读它）
 * @returns 后端返回的 JSON（已经解析成 JS 对象）
 * @throws  ApiError：状态码不是 2xx 时抛出，message 是后端给的提示（FastAPI 放在 detail 字段里），status 是状态码
 */
async function request(path, { method = 'GET', body, userId } = {}) {
  const headers = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json' // 告诉后端：请求体是 JSON
  if (userId) headers['X-User-Id'] = userId

  // fetch：浏览器自带的发请求函数，返回 Promise；await 等它拿到响应头
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  // res.ok：状态码在 200~299 之间。注意：fetch 遇到 4xx / 5xx 不会自己抛错，要自己判断
  if (!res.ok) throw new ApiError(await errorDetail(res), res.status)
  // 【阶段 4】204 = 成功但没有内容（删除接口），没有 JSON 可解析，直接返回 null
  if (res.status === 204) return null
  return res.json()
}

/**
 * 从失败的响应里取出给用户看的提示文字。
 * 【阶段 2 从 request() 里抽出来】流式接口（sse.js）开始推流之前的错误（401 / 403 / 409 / 422）也是普通 JSON，两边共用这一个函数
 * @param {Response} res  状态码不是 2xx 的响应
 * @returns {Promise<string>} 提示文字
 */
export async function errorDetail(res) {
  let detail = `请求失败（HTTP ${res.status}）`
  try {
    const data = await res.json()
    // FastAPI 的错误格式：{"detail": "提示文字"}；422 校验错误时 detail 是一个数组
    if (typeof data.detail === 'string') detail = data.detail
    else if (Array.isArray(data.detail)) detail = '输入内容不符合要求'
  } catch {
    // 响应不是 JSON（比如后端没启动，Vite 返回的 502 页面）：保留上面的默认提示
  }
  return detail
}

/**
 * 发请求失败时抛出的错误，多带一个 status（HTTP 状态码）。
 * 【阶段 4】页面要区分「会话不存在（404，比如在另一个窗口删了）」和其他错误，光有提示文字不够
 */
export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

/** 获取模拟登录的用户列表：[{user_id, name, role}] */
export function fetchUsers() {
  return request('/api/users')
}

/**
 * 发一句话，等 agent 跑完返回结果（阶段 1：不流式）。
 * 【阶段 2】页面已改用 sse.js 的 streamChat；这个函数留着，和后端保留 /api/chat 的原因一样：调试时对照用
 * @param {string} userId     当前用户
 * @param {string|null} threadId  会话 ID；null = 开新对话（后端生成并在响应里返回）
 * @param {string} message    用户输入
 * @returns {thread_id, answer, tool_calls, sources, pending_approvals, token_usage}
 */
export function sendChat(userId, threadId, message) {
  return request('/api/chat', {
    method: 'POST',
    userId,
    body: { thread_id: threadId, message },
  })
}

// ---------------- 【阶段 4】会话管理（后端 routers/threads.py） ----------------

/** 当前用户的会话列表：[{thread_id, title, created_at, updated_at}]，最近聊过的在前 */
export function fetchThreads(userId) {
  return request('/api/threads', { userId })
}

/**
 * 一段对话的聊天记录：[{id, role, text, tools, sources, pending, decision, stopped, error}]
 * 形状和页面上的消息一样，拿到后可以直接交给 MessageBubble 显示
 */
export function fetchHistory(userId, threadId) {
  return request(`/api/threads/${threadId}/messages`, { userId })
}

/** checkpointer 存档里的 State：{thread_id, current_order_id, token_usage, memory_messages} */
export function fetchThreadState(userId, threadId) {
  return request(`/api/threads/${threadId}/state`, { userId })
}

/** 删除会话（会话、聊天记录、模型记忆一起删，找不回来） */
export function deleteThread(userId, threadId) {
  return request(`/api/threads/${threadId}`, { method: 'DELETE', userId })
}

/**
 * 【阶段 5】读存好的会话小结：{summary, created_at, message_count, stale}；还没生成过返回 null
 * stale = true：生成之后又聊过，小结只代表之前的对话
 */
export function fetchSummary(userId, threadId) {
  return request(`/api/threads/${threadId}/summary`, { userId })
}

/** 【阶段 5】生成（或重新生成）小结：后端调用一次 DeepSeek，要等几秒；返回值和 fetchSummary 一样 */
export function generateSummary(userId, threadId) {
  return request(`/api/threads/${threadId}/summary`, { method: 'POST', userId })
}

/**
 * 【阶段 5】checkpointer 里的原始消息链（调试面板用）：
 * [{index, type: human/ai/tool, text, length, tool_calls: [{id, name, args}], tool_call_id, tool_name, status, is_summary}]
 */
export function fetchChain(userId, threadId) {
  return request(`/api/threads/${threadId}/chain`, { userId })
}

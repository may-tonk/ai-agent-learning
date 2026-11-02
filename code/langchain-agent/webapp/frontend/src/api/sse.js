// 【v2 网页版新增 · 阶段 2】调用流式接口 POST /api/chat/stream，边收边解析 SSE 事件
// 【阶段 3】加了 resumeChat（审批后继续，POST /api/chat/resume）和 signal 参数（「停止」按钮）
//
// 【在整体流程里的位置】
//   App.jsx 的 send() → 本文件 streamChat(..., onEvent)
//   → fetch 拿到响应后，不等它结束，一块一块地读响应体（ReadableStream）
//   → 每拼出一条完整的 SSE 事件，就调用 onEvent(事件名, 数据) → App 更新页面（文字一点点长出来）
//   事件有哪些、带什么字段：见后端 webapp/backend/streaming/protocol.py
//
// 【为什么不用浏览器自带的 EventSource】
//   EventSource 是浏览器专门收 SSE 的工具，但它只能发 GET 请求、不能带请求体，也不能自定义请求头。
//   我们要用 POST 发问题、用 X-User-Id 请求头表示登录用户，所以用 fetch 自己读、自己解析。
//   真实项目（包括 ChatGPT 网页版）基本都是这个做法。
import { errorDetail } from './client.js'

/**
 * 发一句话，用流式接口接收回答。
 * @param {string} userId        当前用户（放进 X-User-Id 请求头）
 * @param {string|null} threadId 会话 ID；null = 开新对话
 * @param {string} message       用户输入
 * @param {(event: string, data: object) => void} onEvent  每收到一条事件调用一次
 * @param {AbortSignal} [signal] 【阶段 3】「停止」按钮用：signal 被触发时，fetch 和读流都会立刻中断
 * @returns {Promise<void>} 整个流读完时结束
 * @throws  Error：开始推流之前就失败（401 / 403 / 409 / 422，或后端没启动）；
 *          开始推流之后的错误不会抛出，而是作为 error 事件交给 onEvent；
 *          点了停止：抛出 name 为 'AbortError' 的错误
 */
export function streamChat(userId, threadId, message, onEvent, signal) {
  return postStream('/api/chat/stream', userId, { thread_id: threadId, message }, onEvent, signal)
}

/**
 * 【阶段 3】对停在审批上的对话做决定，然后接着接收后面的回答（后端 POST /api/chat/resume）。
 * 事件和 streamChat 完全一样：批准时会先有 tool_started / tool_finished（工具真的执行了），然后是模型的回答
 * @param {boolean} approved  true 批准 / false 拒绝
 * @param {string} reason     拒绝理由，可以是空字符串
 * 其余参数、返回值、异常同 streamChat
 */
export function resumeChat(userId, threadId, approved, reason, onEvent, signal) {
  return postStream('/api/chat/resume', userId, { thread_id: threadId, approved, reason }, onEvent, signal)
}

/**
 * 【阶段 3 从 streamChat 里抽出来】发一个 POST 请求，边收边解析 SSE 事件。
 * 两个流式接口只有「地址」和「请求体」不同，读流、拆事件的代码完全一样，所以只写一份。
 */
async function postStream(url, userId, body, onEvent, signal) {
  // signal：AbortController 的「信号」。把它交给 fetch，之后调用 controller.abort()：
  //   还在等响应 → fetch 直接抛 AbortError；已经在读流 → reader.read() 抛 AbortError，同时浏览器关闭这个连接
  //   连接一关，后端 StreamingResponse 发现浏览器断开，取消正在跑的 agent（见 backend/streaming/runner.py 的 finally）
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': userId },
    body: JSON.stringify(body),
    signal,
  })
  // 还没开始推流就被拒绝：响应体是普通 JSON 错误，和 client.js 的普通请求一样处理
  if (!res.ok) throw new Error(await errorDetail(res))

  // res.body：响应体是一个 ReadableStream（可读流）。getReader() 拿到读取器，每次 read() 读到「当前已到达」的一块字节
  const reader = res.body.getReader()
  // TextDecoder：把字节解码成文字。{ stream: true } 很重要：
  //   一个汉字在 UTF-8 里占 3 个字节，网络上一块数据的边界可能正好把一个汉字切成两半，
  //   stream: true 会把半个字先留着，等下一块到了再拼完整，否则会出现乱码
  const decoder = new TextDecoder()
  let buffer = '' // 还没凑成一条完整事件的文字

  while (true) {
    // done = true：服务器已经把响应写完、关闭了连接
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 用「一个空行」（\n\n）分隔事件。一块数据里可能有好几条事件，也可能只有半条：
    //   按 \n\n 切开，最后一段可能不完整，放回 buffer 等下一块数据
    const parts = buffer.split('\n\n')
    buffer = parts.pop()
    for (const part of parts) {
      const parsed = parseEvent(part)
      if (parsed) onEvent(parsed.event, parsed.data)
    }
  }
}

/**
 * 解析一条 SSE 事件文本：
 *   event: token
 *   data: {"text": "您好", "call": 1}
 * @returns {{event: string, data: object} | null}  不是完整事件（例如以冒号开头的注释行）时返回 null
 */
function parseEvent(text) {
  let event = 'message' // SSE 规定：没写 event: 行时，事件名默认是 message
  let data = ''
  for (const line of text.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice('event: '.length)
    else if (line.startsWith('data: ')) data += line.slice('data: '.length)
  }
  if (!data) return null
  return { event, data: JSON.parse(data) }
}

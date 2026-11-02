"""
Day 4 · 07：故障演练 —— 故意制造 agent 开发中最常见的问题，看代码怎么表现、该怎么处理

01～06 都是"一切正常"时的样子。真实项目里，大部分时间花在处理不正常的情况上：
key 错了、网络超时、模型输出不合格、一条失败拖垮一批、流式输出中途断掉……
本文件把这些情况一个个"模拟"出来。大部分用假客户端（mock），不花钱；标了 [真实 API] 的会真的请求 DeepSeek。

运行：
    python code/day04-agent-upgrade/07_failure_drills.py            # 全部演练
    python code/day04-agent-upgrade/07_failure_drills.py --case 3   # 只跑第 3 个
演练列表：
    1. [真实 API] API key 错误                → 401 AuthenticationError，重试没有意义
    2. [真实 API] 模型名写错                  → 400/404，同样是"改配置"的问题
    3. [真实 API] 请求超时 + SDK 自动重试      → 看清 timeout 和 max_retries 的作用
    4. [真实 API] max_tokens 太小，JSON 被截断 → 校验报 json_invalid，进入重试
    5. [mock]     模型前两次输出不合格         → analyze_ticket 的重试机制如何把它救回来
    6. [mock]     模型一直输出不合格           → 重试用完，抛出 TicketParseError
    7. [mock]     并发时一条失败               → gather 有没有 return_exceptions=True 的区别
    8. [mock]     流式输出中途断开             → 已经打印的内容收不回来，要怎么兜底
"""
import argparse
import asyncio
import time
from types import SimpleNamespace

from openai import (APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI,
                    AuthenticationError, OpenAI)

from common import BASE_URL, EXTRA_BODY, MODEL, TICKETS, get_client
from ticket import TicketParseError, analyze_ticket, analyze_ticket_async, build_messages, check


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


# ============================================================
# 假客户端：结构和 OpenAI SDK 返回的对象一样（resp.choices[0].message.content、resp.usage.xxx），
# 但内容由我们事先写好。这就是单元测试里常说的 mock：不连网络、不花钱、结果可控。
# ============================================================
def fake_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=450, completion_tokens=50),
    )


class FakeClient:
    """按顺序返回 outputs 里的内容，每次调用 create 返回下一个"""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        return fake_response(self.outputs.pop(0))


GOOD = '{"intent": "申请退款", "order_id": "ORD100021", "sentiment": "neutral", "urgency": 3, "needs_human": false, "summary": "耳机左耳无声，询问能否退款"}'


# ============================================================
# 1. API key 错误
# ============================================================
def case_1():
    title("1. [真实 API] API key 错误")
    client = OpenAI(api_key="sk-this-is-a-wrong-key", base_url=BASE_URL)
    try:
        client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "你好"}], max_tokens=5)
    except AuthenticationError as e:
        print(f"捕获到 {type(e).__name__}，HTTP 状态码 {e.status_code}")
        print(f"服务端返回：{e.message[:150]}")
    print("""
要点：
  - 401 = 身份验证失败。原因只可能是 key 错了、过期了、被删了，或者没读到 .env
  - 这类错误重试多少次都一样，应该立刻失败并报清楚原因（common.py 的 _api_key() 在没有 key 时就直接退出）
  - 工程上：启动服务时先发一个很小的请求检查 key（健康检查），而不是等第一个用户来了才发现""")


# ============================================================
# 2. 模型名写错
# ============================================================
def case_2():
    title("2. [真实 API] 模型名写错")
    client = get_client()
    try:
        client.chat.completions.create(model="deepseek-flashh", messages=[{"role": "user", "content": "你好"}], max_tokens=5)
    except APIStatusError as e:      # 4xx / 5xx 错误的共同父类
        print(f"捕获到 {type(e).__name__}，HTTP 状态码 {e.status_code}")
        print(f"服务端返回：{e.message[:150]}")
    print("""
要点：
  - 4xx 都是"请求本身有问题"：参数错、模型名错、内容太长……重试没用，要改代码或配置
  - 5xx 和 429（请求太多）才是"可以等一会儿再试"的错误
  - 本项目的模型名来自 common.py：MODEL = os.environ.get("AGENT_MODEL", "deepseek-flash")，
    想换模型只改环境变量，不用改代码。这是"配置和代码分离"的习惯""")


# ============================================================
# 3. 超时 + 自动重试
# ============================================================
def case_3():
    title("3. [真实 API] 请求超时 + SDK 自动重试")
    for retries in (0, 2):
        # timeout=0.05 秒：网络请求根本来不及完成，一定超时
        client = OpenAI(api_key=get_client().api_key, base_url=BASE_URL, timeout=0.05, max_retries=retries)
        t = time.perf_counter()
        try:
            client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": "你好"}], max_tokens=5)
        except (APITimeoutError, APIConnectionError) as e:
            print(f"max_retries={retries}：{time.perf_counter() - t:.2f}s 后抛出 {type(e).__name__}")
    print("""
要点：
  - OpenAI SDK 默认 timeout=600 秒、max_retries=2：超时、连接失败、429、5xx 会自动重试 2 次，中间等待时间逐渐变长（指数退避）
  - 所以 max_retries=2 时，耗时明显比 0 次长：SDK 在背后多试了两次
  - 默认 600 秒对在线服务太长了：用户早就走了。工程上会按场景设置，比如对话接口 30～60 秒
  - 设置方法：OpenAI(timeout=30, max_retries=3)，或者单次请求 client.with_options(timeout=10).chat.completions.create(...)""")


# ============================================================
# 4. max_tokens 太小
# ============================================================
def case_4():
    title("4. [真实 API] max_tokens 太小，JSON 被截断")
    client = get_client()
    resp = client.chat.completions.create(model=MODEL, messages=build_messages(TICKETS[0]),
                                          response_format={"type": "json_object"}, max_tokens=20, temperature=0,
                                          extra_body=EXTRA_BODY)
    content = resp.choices[0].message.content
    print(f"finish_reason = {resp.choices[0].finish_reason}   ← length 表示是被 max_tokens 截断的，不是模型自己说完的")
    print(f"模型输出：{content}")
    _, feedback = check(content)
    print(f"校验结果：{feedback}")
    print("""
要点：
  - JSON 模式只保证"模型想输出 JSON"，max_tokens 不够时照样被拦腰截断，变成坏 JSON
  - 判断方法：看 finish_reason。stop = 正常结束；length = 被截断；tool_calls = 要调工具
  - 这种情况重试也没用（每次都截断在同一个地方），正确做法是把 max_tokens 调大（ticket.py 里设的是 300）
  - 工程上：日志里要记录 finish_reason，出现 length 就报警""")


# ============================================================
# 5. 前两次不合格，第三次合格
# ============================================================
def case_5():
    title("5. [mock] 模型前两次输出不合格，重试把它救回来")
    client = FakeClient([
        "",                                                               # 第 1 次：空内容（DeepSeek 文档说 JSON 模式偶尔会这样）
        '{"intent": "退货", "order_id": "ORD100021", "urgency": 9}',       # 第 2 次：枚举值错、超范围、缺字段
        GOOD,                                                             # 第 3 次：合格
    ])
    r = analyze_ticket(client, TICKETS[0], verbose=True)
    print(f"\n最终结果：第 {r.attempts} 次成功，累计 tokens 输入 {r.prompt_tokens} / 输出 {r.completion_tokens}")
    print("""
要点：
  - 每次失败，代码把"模型的错误输出 + 具体错在哪"追加进对话，模型下一次才知道要改什么（ticket.py 第 113 行）
  - 代价：tokens 是累加的，重试 2 次 ≈ 花了 3 倍的钱，而且对话越来越长
  - 所以重试次数要有上限（MAX_ATTEMPTS = 3），并且要统计"平均第几次成功"，太高说明提示词或 schema 该改了""")


# ============================================================
# 6. 一直不合格
# ============================================================
def case_6():
    title("6. [mock] 模型一直输出不合格，重试次数用完")
    client = FakeClient(['{"intent": "退货"}'] * 3)
    try:
        analyze_ticket(client, TICKETS[0])
    except TicketParseError as e:
        print(f"调用了 {client.calls} 次模型后抛出 TicketParseError：\n  {e}")
    print("""
要点：
  - 重试不是万能的。用完次数后要有明确的失败出口，不能无限循环
  - 失败之后怎么办是业务决定：server.py 里返回 HTTP 502（上游没给出合格结果）；
    客服系统里通常是"转人工"——宁可慢一点，也不能拿一个错误的分析结果去自动处理""")


# ============================================================
# 7. 并发时一条失败
# ============================================================
class FakeAsyncClient:
    """异步版本：第 bad_index 条工单的请求会抛出连接错误，其他正常返回"""

    def __init__(self, bad_text):
        self.bad_text = bad_text
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        await asyncio.sleep(0.2)                             # 假装在等网络
        if kwargs["messages"][1]["content"] == self.bad_text:
            raise ConnectionError("模拟：这条请求网络断了")
        return fake_response(GOOD)


async def case_7_async():
    tickets = TICKETS[:5]
    client = FakeAsyncClient(bad_text=tickets[2])           # 第 3 条会失败

    print("1) gather 不加 return_exceptions：")
    try:
        results = await asyncio.gather(*(analyze_ticket_async(client, t) for t in tickets))
        print(f"   拿到 {len(results)} 个结果")
    except ConnectionError as e:
        print(f"   整个 gather 抛出异常：{e}\n   → 其他 4 条明明成功了，结果却全拿不到")

    print("2) gather 加 return_exceptions=True（04 和 server.py 的写法）：")
    results = await asyncio.gather(*(analyze_ticket_async(client, t) for t in tickets), return_exceptions=True)
    for i, r in enumerate(results, 1):
        print(f"   #{i} {'失败：' + str(r) if isinstance(r, Exception) else '成功：' + r.analysis.intent}")


def case_7():
    title("7. [mock] 并发处理 5 条工单，其中第 3 条失败")
    asyncio.run(case_7_async())
    print("""
要点：
  - 批量任务里"一条失败"是常态（网络抖动、某条内容特殊），绝不能让它拖垮整批
  - return_exceptions=True：异常被当成结果放在对应位置，之后逐条判断 isinstance(r, Exception)
  - 工程上还会把失败的条目记下来，稍后单独重跑（重试队列），而不是整批重来""")


# ============================================================
# 8. 流式输出中途断开
# ============================================================
def fake_stream():
    for piece in ["您好，您的订单", " ORD100023 ", "已经发货，", "预计"]:
        time.sleep(0.2)
        yield piece
    raise ConnectionError("模拟：网络中断，流断开了")


def case_8():
    title("8. [mock] 流式输出到一半，网络断了")
    received = []
    try:
        for piece in fake_stream():
            print(piece, end="", flush=True)
            received.append(piece)
    except ConnectionError as e:
        print(f"\n\n捕获到：{e}")
        print(f"已经显示给用户的内容：{''.join(received)!r}（收不回来了）")
    print("""
要点：
  - 非流式请求失败了可以整体重试，用户什么也没看到；流式失败时，前半句已经显示出去了
  - HTTP 状态码 200 在流开始时就已经发出，没法再改成 500。所以 server.py 的 agent_events
    用 try/except 包住整个流，出错时发一个 {"type": "error"} 事件，让前端显示"回答中断，请重试"
  - 工程上：前端收到 error 事件后保留已显示的内容并提示用户；后端记录日志，方便排查是哪一步断的""")


CASES = {1: case_1, 2: case_2, 3: case_3, 4: case_4, 5: case_5, 6: case_6, 7: case_7, 8: case_8}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int, choices=list(CASES), help="只运行某一个演练")
    args = parser.parse_args()
    for n in ([args.case] if args.case else CASES):
        CASES[n]()

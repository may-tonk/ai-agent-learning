"""
Day 4 · 04：asyncio 并发 —— 同时处理多条工单

调用 LLM 的大部分时间，程序都在"等网络返回"，CPU 其实闲着。
同步写法：等第 1 个返回 → 再发第 2 个 → ……，10 条工单的总时间 = 10 次等待相加。
异步写法：先把 10 个请求都发出去，谁先回来先处理谁，总时间 ≈ 最慢的那几次。

运行：
    python code/day04-agent-upgrade/04_async_concurrency.py
    python code/day04-agent-upgrade/04_async_concurrency.py --n 5      # 只用前 5 条工单（省时间省 token）

A. 不调 API，用 asyncio.sleep 模拟"等待"，先看懂 async / await / gather 的效果
B. 真实调用：同一批工单，一条条处理 vs asyncio.gather 并发（Semaphore 限制最多同时 3 个）
"""
import argparse
import asyncio
import time

from common import TICKETS, get_async_client
from ticket import analyze_ticket_async

T0 = time.perf_counter()


def now():
    """从程序启动到现在过了几秒，用来看清楚每件事发生的先后"""
    return f"{time.perf_counter() - T0:6.2f}s"


def title(text):
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}")


# ============================================================
# A. asyncio 基础
# ============================================================
async def fake_llm_call(name, seconds):
    # async def 定义的是"协程函数"，调用它不会立刻执行，而是得到一个协程对象，要 await 或交给事件循环才会跑
    print(f"  {now()}  {name} 发出请求")
    await asyncio.sleep(seconds)     # await：我要等一会儿，这段时间事件循环可以去跑别的协程
    print(f"  {now()}  {name} 收到结果")
    return f"{name} 的结果"


async def blocking_call(name, seconds):
    print(f"  {now()}  {name} 发出请求")
    time.sleep(seconds)              # 错误示范：time.sleep 是同步阻塞的，整个事件循环都被卡住，谁也跑不了
    print(f"  {now()}  {name} 收到结果")
    return f"{name} 的结果"


async def part_a():
    title("A. asyncio 基础：3 个各需 1 秒的请求")

    print("\n1) 一个接一个 await（顺序执行）")
    t = time.perf_counter()
    for name in ["请求1", "请求2", "请求3"]:
        await fake_llm_call(name, 1)
    print(f"  总耗时 {time.perf_counter() - t:.2f}s")

    print("\n2) asyncio.gather 一起等（并发执行）")
    t = time.perf_counter()
    # gather 把多个协程交给事件循环同时推进；返回值的顺序和传入顺序一致（不是完成顺序）
    results = await asyncio.gather(fake_llm_call("请求1", 1), fake_llm_call("请求2", 1), fake_llm_call("请求3", 1))
    print(f"  总耗时 {time.perf_counter() - t:.2f}s，结果：{results}")

    print("\n3) gather 了，但协程里用了 time.sleep（阻塞调用）")
    t = time.perf_counter()
    await asyncio.gather(blocking_call("请求1", 1), blocking_call("请求2", 1), blocking_call("请求3", 1))
    print(f"  总耗时 {time.perf_counter() - t:.2f}s ← 又变回 3 秒：async 函数里一旦有阻塞调用，并发就失效了")
    print("  （同理：在 async 函数里用同步的 OpenAI 客户端也会卡住，必须用 AsyncOpenAI + await）")


# ============================================================
# B. 真实调用 DeepSeek
# ============================================================
async def analyze_one(client, i, text, sem=None):
    """分析一条工单，并打印开始/结束时间。sem 不为空时，先拿到"许可证"才能发请求。"""
    async def run():
        print(f"  {now()}  #{i:<2} 开始")
        try:
            r = await analyze_ticket_async(client, text)
        except Exception as e:
            print(f"  {now()}  #{i:<2} 失败  {type(e).__name__}: {e}")
            raise                      # 继续往外抛，交给调用方决定怎么处理
        print(f"  {now()}  #{i:<2} 完成  {r.analysis.intent}/{r.analysis.sentiment}/紧急{r.analysis.urgency}  {r.analysis.summary}")
        return r

    if sem is None:
        return await run()
    # Semaphore(3) 就像只有 3 张许可证：同一时刻最多 3 个请求在飞，其余的在这里排队。
    # 原因：API 有速率限制（每分钟请求数），一次发几百个会被拒绝（HTTP 429）
    async with sem:
        return await run()


async def part_b(tickets):
    title(f"B. 真实调用：分析 {len(tickets)} 条工单")
    # async with：用完自动关闭底层的网络连接
    async with get_async_client() as client:
        print("\n1) 顺序处理：await 完一条再处理下一条")
        t = time.perf_counter()
        for i, text in enumerate(tickets, 1):
            try:
                await analyze_one(client, i, text)
            except Exception:
                pass                   # 失败信息上面已经打印了，这里跳过，继续下一条
        seq = time.perf_counter() - t
        print(f"  顺序总耗时 {seq:.2f}s")

        print("\n2) 并发处理：asyncio.gather + Semaphore(3)")
        sem = asyncio.Semaphore(3)
        t = time.perf_counter()
        # return_exceptions=True：某一条失败时，不让整个 gather 抛异常，而是把异常对象放在结果列表对应位置
        results = await asyncio.gather(*(analyze_one(client, i, text, sem) for i, text in enumerate(tickets, 1)),
                                       return_exceptions=True)
        conc = time.perf_counter() - t
        print(f"  并发总耗时 {conc:.2f}s")

    ok = [r for r in results if not isinstance(r, Exception)]
    failed = [(i, r) for i, r in enumerate(results, 1) if isinstance(r, Exception)]
    print(f"\n顺序 {seq:.2f}s vs 并发 {conc:.2f}s，快了 {seq / conc:.1f} 倍")
    print(f"成功 {len(ok)} 条，失败 {len(failed)} 条；共用 tokens：输入 {sum(r.prompt_tokens for r in ok)}，"
          f"输出 {sum(r.completion_tokens for r in ok)}")
    for i, e in failed:
        print(f"  #{i} 失败：{type(e).__name__}: {e}")
    print("观察要点：并发时'开始'最多同时有 3 个，完成的顺序是乱的（谁先返回谁先打印），"
          "但 gather 返回的 results 顺序和工单顺序一致。")


async def main(n):
    await part_a()
    await part_b(TICKETS[:n])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=len(TICKETS), help="用前几条工单")
    # asyncio.run：创建事件循环，运行 main() 这个协程直到结束，然后关闭事件循环。程序入口只调用一次
    asyncio.run(main(parser.parse_args().n))

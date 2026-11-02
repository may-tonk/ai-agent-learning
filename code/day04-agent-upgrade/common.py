"""
Day 4 公共代码：几个示例文件都要用到的配置、客户端和数据。

这个文件本身不演示新知识，只是避免每个文件都重复写一遍：
  - 读取项目根目录的 .env
  - 创建同步客户端 OpenAI 和异步客户端 AsyncOpenAI（都指向 DeepSeek）
  - 读取 Day 7 的模拟订单数据（直接复用 code/day07-order-agent/data/orders.json）
  - 10 条模拟的客服工单，供 02 / 04 / server 使用
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

# 本文件在 项目根目录/code/day04-agent-upgrade/ 下，往上两层是项目根目录，.env 在那里
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MODEL = os.environ.get("AGENT_MODEL", "deepseek-flash")
BASE_URL = "https://api.deepseek.com"

# deepseek-flash 默认开启"思考模式"：先输出一段推理（reasoning_content），再输出正式回答。
# 思考会占用 max_tokens、拖慢第一个字出现的时间，而且思考模式不支持强制指定工具（tool_choice），
# Day 4 的演示都是简单任务，所以统一关掉。每次请求都传 extra_body=EXTRA_BODY。
# extra_body：OpenAI SDK 不认识的参数（DeepSeek 自己的扩展）原样放进请求体发给服务端。
EXTRA_BODY = {"thinking": {"type": "disabled"}}

# 复用 Day 7 的订单数据，不再复制一份
ORDERS_FILE = PROJECT_ROOT / "code" / "day07-order-agent" / "data" / "orders.json"


def _api_key():
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        sys.exit("没有找到 DEEPSEEK_API_KEY：请在项目根目录的 .env 文件里填上你的 key")
    return key


def get_client():
    """同步客户端：调用 client.chat.completions.create(...) 时，程序会停在这里等结果返回。"""
    return OpenAI(api_key=_api_key(), base_url=BASE_URL)


def get_async_client():
    """异步客户端：用法和同步版几乎一样，只是调用前要加 await。
    等待网络返回的这段时间，事件循环可以去执行别的任务（这就是并发的来源）。"""
    return AsyncOpenAI(api_key=_api_key(), base_url=BASE_URL)


def load_orders():
    return json.loads(ORDERS_FILE.read_text(encoding="utf-8"))


# 10 条模拟工单：有查询、物流、退款、投诉、表扬、咨询，情绪和紧急程度各不相同
TICKETS = [
    "我的蓝牙耳机（订单 ORD100021）左耳没声音了，能退款吗？",
    "ORD100023 到哪了？说好放快递柜的",
    "你们这什么破键盘，ORD100031 用了两天就有键失灵，太失望了！！",
    "想问一下下单以后还能不能改收货地址",
    "ORD100040 付款三天了还不发货，今天再不发我就去投诉了",
    "谢谢，上次的退款已经收到了，客服态度很好",
    "ORD100048 的显示器有坏点，金额比较大，麻烦尽快处理",
    "帮我查一下 bob@example.com 名下有哪些订单",
    "ORD100052 物流好几天没更新了，是不是丢件了？",
    "你们支持开电子发票吗",
]

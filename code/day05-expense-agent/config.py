"""
配置集中放在这一个文件里：路径、模型、接口地址、各种上限。

真实项目的习惯：配置和业务代码分开。要换模型、换服务商、调上限时只改这里（或者改 .env），
不用去翻工具和 agent 循环的代码。敏感信息（API key）只从环境变量读，绝不写进代码。
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# ---------- 路径 ----------
DAY_DIR = Path(__file__).resolve().parent          # code/day05-expense-agent/
PROJECT_ROOT = DAY_DIR.parents[1]                   # E:\agent学习任务
DATA_DIR = DAY_DIR / "data"
CLAIMS_DIR = DATA_DIR / "claims"
POLICY_FILE = DATA_DIR / "policy.md"
EVAL_FILE = DATA_DIR / "eval_cases.json"
PROMPTS_DIR = DAY_DIR / "prompts"
LOGS_DIR = DAY_DIR / "logs"                         # 运行记录，已被 .gitignore 忽略

load_dotenv(PROJECT_ROOT / ".env")

# ---------- 模型和接口 ----------
# 和 Day 4 一样默认用 deepseek-flash。想换模型就在 .env 里改 AGENT_MODEL。
MODEL = os.environ.get("AGENT_MODEL", "deepseek-flash")

# OpenAI 协议的地址。默认指向 DeepSeek；以后有 OpenAI 的 key，
# 在 .env 里设 LLM_BASE_URL=https://api.openai.com/v1、LLM_API_KEY=sk-...、AGENT_MODEL=gpt-xxx 即可，代码不用改。
BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com")
# DeepSeek 的严格模式（strict 工具调用）是 Beta 功能，必须走 /beta 地址（Day 4 的 02 已验证）。
# OpenAI 官方接口本身就支持 strict，不需要换地址。
STRICT_BASE_URL = os.environ.get("LLM_STRICT_BASE_URL", "https://api.deepseek.com/beta" if "deepseek" in BASE_URL else BASE_URL)

# Anthropic 协议的地址：DeepSeek 也提供 Anthropic 兼容接口，所以用同一把 DeepSeek key 就能跑 Anthropic 协议。
# 文档：https://api-docs.deepseek.com/guides/anthropic_api
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_COMPAT_BASE_URL", "https://api.deepseek.com/anthropic")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_COMPAT_MODEL", MODEL)

IS_DEEPSEEK = "deepseek" in BASE_URL
# deepseek-flash 默认开"思考模式"，会拖慢速度、占用 token，审核这种任务不需要，统一关掉（同 Day 4）。
# 这是 DeepSeek 自己的扩展参数；如果换成 OpenAI 官方接口，就不能传，否则会报参数错误。
EXTRA_BODY = {"thinking": {"type": "disabled"}} if IS_DEEPSEEK else {}

# ---------- agent 的各种上限 ----------
MAX_STEPS = 15              # 一张报销单最多和模型来回 15 轮，防止死循环烧钱
MAX_TOOL_CHARS = 4000       # v2 工具结果的长度上限，超过时明确告诉模型"已截断"
TEMPERATURE = 0             # 审核要求结果稳定可复现，不需要创造性


def api_key():
    """优先读 LLM_API_KEY（换服务商时用），否则读 DEEPSEEK_API_KEY。"""
    key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        sys.exit("没有找到 API key：请在项目根目录的 .env 里填好 DEEPSEEK_API_KEY")
    return key


def get_openai_client(strict=False):
    """OpenAI 协议的客户端。strict=True 时连到支持严格模式的地址。"""
    from openai import OpenAI   # 放在函数里导入：只跑单元测试时不需要真的连网
    return OpenAI(api_key=api_key(), base_url=STRICT_BASE_URL if strict else BASE_URL)


def get_anthropic_client():
    """Anthropic 协议的客户端（指向 DeepSeek 的 Anthropic 兼容接口）。只在协议对比脚本里用。"""
    import anthropic
    return anthropic.Anthropic(api_key=api_key(), base_url=ANTHROPIC_BASE_URL)

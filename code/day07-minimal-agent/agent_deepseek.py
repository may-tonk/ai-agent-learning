"""
最小 agent —— DeepSeek 版（约 50 行核心逻辑，不用任何框架）

骨架 = LLM + 循环 + 工具 + 上下文(messages)
任务示例：找出目录里所有 TODO 注释，汇总成 markdown 文件。

DeepSeek 的接口和 OpenAI 完全兼容，所以直接用 openai 这个 SDK，
只要把 base_url 指向 DeepSeek 即可。

运行（在 PyCharm 终端，确认开头有 (.venv)）：
    python -m pip install -r requirements.txt      # 在项目根目录执行，装好所有依赖
    在项目根目录的 .env 文件里填好 DEEPSEEK_API_KEY
    python code/day07-minimal-agent/agent_deepseek.py
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# 读取 .env 文件，把里面的 KEY=VALUE 写进环境变量（相当于自动帮你执行了 $env:KEY="VALUE"）。
# 本文件在 项目根目录/code/day07-minimal-agent/ 下，往上两层就是项目根目录，.env 就放在那里。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MODEL = os.environ.get("AGENT_MODEL", "deepseek-chat")
MAX_STEPS = 15          # 最大步数：防止模型无限循环、烧钱
MAX_OUTPUT = 5000       # 工具输出截断：防止一个大文件撑爆上下文

# ---------- 1. 工具：真正干活的是你的代码，不是模型 ----------
def list_files(path="."):
    return "\n".join(str(p) for p in Path(path).rglob("*") if p.is_file())

def read_file(path):
    return Path(path).read_text(encoding="utf-8", errors="replace")

def write_file(path, content):
    Path(path).write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"

TOOL_FUNCS = {"list_files": list_files, "read_file": read_file, "write_file": write_file}

# ---------- 2. 工具说明书：模型只能看到这个 JSON Schema ----------
# OpenAI 格式：每个工具外面包一层 {"type": "function", "function": {...}}，参数字段叫 parameters
def tool(name, description, properties, required=()):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}

TOOLS = [
    tool("list_files", "递归列出目录下所有文件的路径",
         {"path": {"type": "string", "description": "目录路径，默认 ."}}),
    tool("read_file", "读取一个文本文件的全部内容", {"path": {"type": "string"}}, ["path"]),
    tool("write_file", "把内容写入文件（会覆盖原文件）",
         {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
]

def run_tool(name, args):
    """执行工具。出错时不崩溃，而是把错误信息当结果返回给模型，让它自己纠正。"""
    try:
        return str(TOOL_FUNCS[name](**args))[:MAX_OUTPUT]
    except Exception as e:
        return f"工具出错: {type(e).__name__}: {e}"

# ---------- 3. agent 循环：整个 agent 的核心 ----------
def run_agent(task, client=None):
    if client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            sys.exit("没有找到 DEEPSEEK_API_KEY：请在项目根目录的 .env 文件里填上你的 key")
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    messages = [  # 上下文 = 你自己维护的列表（模型无状态）
        {"role": "system", "content": "你是一个文件助手，使用工具完成任务，完成后简要总结。"},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS)
        choice = resp.choices[0]
        msg = choice.message
        print(msg)
        messages.append(msg)  # 模型的回复（包括它想调用哪些工具）也要放回历史

        if msg.content:
            print(f"[第{step}步 思考] {msg.content}")

        # finish_reason 不是 tool_calls，说明模型认为任务完成了 → 退出循环
        if choice.finish_reason != "tool_calls":
            return msg.content

        # 模型并没有"调用"工具，它只是输出了调用意图；真正执行的是这里
        for call in msg.tool_calls:
            args = json.loads(call.function.arguments)   # 注意：参数是 JSON 字符串，要自己解析
            print(f"[第{step}步 工具] {call.function.name}({json.dumps(args, ensure_ascii=False)[:200]})")
            output = run_tool(call.function.name, args)
            # 每个工具结果单独一条，role 是 tool，用 tool_call_id 对应到是哪次调用
            messages.append({"role": "tool", "tool_call_id": call.id, "content": output})

    return f"达到最大步数 {MAX_STEPS}，强制停止"

if __name__ == "__main__":
    # 切换到本文件所在目录，这样 ./demo 这种相对路径不管你从哪个目录运行都能找到
    os.chdir(Path(__file__).parent)
    task = sys.argv[1] if len(sys.argv) > 1 else "找出 ./demo 目录里所有 TODO 注释，汇总写入 todo_report.md"
    print("\n最终答案：", run_agent(task))

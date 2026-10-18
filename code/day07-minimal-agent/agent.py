"""
最小 agent（约 50 行核心逻辑，不用任何框架）

骨架 = LLM + 循环 + 工具 + 上下文(messages)
任务示例：找出目录里所有 TODO 注释，汇总成 markdown 文件。

Anthropic 版（需要 Anthropic 的 key）。你用的是 DeepSeek，请运行 agent_deepseek.py。

运行：
    python -m pip install -r requirements.txt      # 在项目根目录执行
    在项目根目录的 .env 文件里填好 ANTHROPIC_API_KEY
    python code/day07-minimal-agent/agent.py
"""
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

# 读取项目根目录（本文件往上两层）.env 里的 ANTHROPIC_API_KEY
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
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
TOOLS = [
    {"name": "list_files", "description": "递归列出目录下所有文件的路径",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径，默认 ."}}}},
    {"name": "read_file", "description": "读取一个文本文件的全部内容",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file", "description": "把内容写入文件（会覆盖原文件）",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"]}},
]

def run_tool(name, args):
    """执行工具。出错时不崩溃，而是把错误信息当结果返回给模型，让它自己纠正。"""
    try:
        result = str(TOOL_FUNCS[name](**args))
        return result[:MAX_OUTPUT], False
    except Exception as e:
        return f"工具出错: {type(e).__name__}: {e}", True

# ---------- 3. agent 循环：整个 agent 的核心 ----------
def run_agent(task, client=None):
    client = client or anthropic.Anthropic()   # 自动读取 ANTHROPIC_API_KEY
    messages = [{"role": "user", "content": task}]   # 上下文 = 你自己维护的列表（模型无状态）

    for step in range(1, MAX_STEPS + 1):
        resp = client.messages.create(model=MODEL, max_tokens=4096, tools=TOOLS,
                                      system="你是一个文件助手，使用工具完成任务，完成后简要总结。",
                                      messages=messages)
        messages.append({"role": "assistant", "content": resp.content})  # 模型的回复也要放回历史

        for block in resp.content:
            if block.type == "text":
                print(f"[第{step}步 思考] {block.text}")

        # stop_reason 不是 tool_use，说明模型认为任务完成了 → 退出循环
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")

        # 模型并没有"调用"工具，它只是输出了调用意图；真正执行的是这里
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                print(f"[第{step}步 工具] {block.name}({json.dumps(block.input, ensure_ascii=False)[:200]})")
                output, is_error = run_tool(block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                 "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})  # 工具结果以 user 身份喂回去

    return f"达到最大步数 {MAX_STEPS}，强制停止"

if __name__ == "__main__":
    os.chdir(Path(__file__).parent)   # 让 ./demo 始终相对于本文件夹
    task = sys.argv[1] if len(sys.argv) > 1 else "找出 ./demo 目录里所有 TODO 注释，汇总写入 todo_report.md"
    print("\n最终答案：", run_agent(task))

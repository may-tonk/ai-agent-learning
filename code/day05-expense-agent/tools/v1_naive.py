"""
v1：D3 风格的"原始版"工具，作为重构前的对照组。

只有两个通用工具：read_file（读文件）和 calculate（计算），基本照搬 Day 7 minimal-agent 的写法：
  - 说明只有一句话，没讲清楚什么时候用、参数什么格式
  - read_file 返回整个文件，超过 5000 字符就静默截断（和 Day 7 的 MAX_OUTPUT 一样），不告诉模型
  - 出错时直接把异常原文返回（"工具出错: FileNotFoundError: ..."），没有告诉模型下一步怎么做
  - 参数名是笼统的 path / expression，模型要自己拼出 data/claims/C002.json 这样的路径

两个版本只有"数据怎么拿到"不同，提交结论都用同一个 review_submit，这样评测时的对比才公平。
注意：calculate 底层仍然用安全的 safe_eval，不用 eval()。对照组要对比的是"接口设计"，没必要真的留一个安全漏洞。
"""
from pydantic import Field

import config
from tools.base import ToolArgs
from tools.calculator import safe_eval
from tools.registry import Tool, Toolset
from tools.submit import TOOL as SUBMIT_TOOL


class ReadFileArgs(ToolArgs):
    path: str = Field(description="文件路径")


def read_file(args: ReadFileArgs) -> str:
    path = (config.DAY_DIR / args.path).resolve()
    # 唯一保留的保护：只能读 data/ 目录下的文件。这是安全底线，不属于"接口好不好用"的范畴
    if config.DATA_DIR.resolve() not in path.parents:
        raise PermissionError(f"只能读取 data 目录下的文件：{args.path}")
    return path.read_text(encoding="utf-8")   # 文件不存在时直接抛 FileNotFoundError


class CalculateArgs(ToolArgs):
    expression: str = Field(description="表达式")


def calculate(args: CalculateArgs) -> str:
    return str(safe_eval(args.expression))     # 出错直接抛异常


TOOLSET = Toolset(
    name="v1",
    tools=[
        Tool("read_file", "读取一个文本文件的全部内容", ReadFileArgs, read_file),
        Tool("calculate", "计算数学表达式", CalculateArgs, calculate),
        SUBMIT_TOOL,
    ],
    strict=False,
    max_chars=5000,
    announce_truncation=False,
)

# v1 要告诉模型数据放在哪里（v2 不需要，路径是工具内部的事）
DATA_ACCESS = ("报销制度在 data/policy.md；报销单在 data/claims/ 目录下，文件名是 报销单号.json（例如 data/claims/C001.json）。"
               "用 read_file 读取文件，用 calculate 计算。")

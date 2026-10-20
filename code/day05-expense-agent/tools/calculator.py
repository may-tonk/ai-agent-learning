"""
计算类工具：calc_evaluate（算式求值）和 calc_days_between（日期相差天数）。

为什么审核 agent 一定要有计算工具：模型做算术不可靠，尤其是多个数相加、乘法、日期差。
报销金额错一分钱都是事故，所以提示词里要求"所有算术都交给工具"，模型只负责列算式。

为什么不用 eval()：Cookbook 的计算器示例用了 eval，并且自己注明"生产环境不要这样做"。
eval 会执行任意 Python 代码，模型（或者被注入的恶意内容）传一句 __import__('os').system(...) 就能控制你的电脑。
这里用 ast 模块把算式解析成语法树，只允许数字、+ - * / ( ) 和 round/min/max/abs/sum，其他一律拒绝。
"""
import ast
import operator
from datetime import date
from typing import Annotated

from pydantic import Field

from tools.registry import Tool, ToolError, to_json
from tools.base import ToolArgs

_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"round": round, "min": min, "max": max, "abs": abs, "sum": sum}
# 模型常用的中文符号，先统一替换掉，省得它因为一个全角括号白白失败一次（工具要"容错"）
_NORMALIZE = str.maketrans({"×": "*", "÷": "/", "（": "(", "）": ")", "，": ",", "－": "-", "＋": "+"})


def safe_eval(expression: str) -> float:
    """安全地计算一个算术表达式。不合法时抛出 ValueError，消息里说明原因。"""
    if len(expression) > 500:
        raise ValueError("表达式太长（超过 500 字符），请拆成几步分别计算")
    tree = ast.parse(expression.translate(_NORMALIZE), mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("指数不能超过 10")
            return _BIN_OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        if isinstance(node, (ast.List, ast.Tuple)):
            return [ev(x) for x in node.elts]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"不支持的写法：{ast.unparse(node)}")

    result = ev(tree)
    if not isinstance(result, (int, float)):
        raise ValueError("表达式的结果必须是一个数字")
    return result


# ============================================================
# v2 工具：参数模型 + 函数
# ============================================================
class CalcEvaluateArgs(ToolArgs):
    expression: Annotated[str, Field(description="算术表达式，只能包含数字、+ - * / ( ) 以及 round/min/max/abs/sum。"
                                                 "金额不要写千分位逗号和单位。例如：3*600、2340-1800、min(410, 2*150)、sum([626, 760, 210])")]


def calc_evaluate(args: CalcEvaluateArgs) -> str:
    try:
        value = safe_eval(args.expression)
    except ZeroDivisionError:
        raise ToolError("计算失败：除数为 0。请检查表达式")
    except (SyntaxError, ValueError, TypeError) as e:
        # 报错带上"正确写法示例"，模型下一次就能改对
        raise ToolError(f"无法计算 '{args.expression}'：{e}。正确示例：2*600、sum([1150, 1800, 535])、min(410, 300)")
    return f"{args.expression} = {round(value, 2)}"


class CalcDaysBetweenArgs(ToolArgs):
    start_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="开始日期，格式 YYYY-MM-DD")]
    end_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="结束日期，格式 YYYY-MM-DD")]


def calc_days_between(args: CalcDaysBetweenArgs) -> str:
    try:
        start, end = date.fromisoformat(args.start_date), date.fromisoformat(args.end_date)
    except ValueError as e:
        raise ToolError(f"日期不合法：{e}。请使用真实存在的日期，格式 YYYY-MM-DD")
    days = (end - start).days
    return to_json({
        "start_date": args.start_date, "end_date": args.end_date, "days": days,
        # 直接告诉模型这个数字在不同场景下怎么用，减少它自己推理出错的机会
        "how_to_use": "住宿晚数 = days；出差天数 = days + 1；提交是否超过 60 天看 days > 60",
    })


TOOLS = [
    Tool("calc_evaluate",
         "计算算术表达式，返回精确结果。审核中所有加减乘除（求和、按晚/按天计算标准、核减金额）都必须用这个工具算，不要心算。"
         "可以一次传一个完整算式，例如 sum([1150, 1800, 535, 85, 1150])。",
         CalcEvaluateArgs, calc_evaluate),
    Tool("calc_days_between",
         "计算两个日期相差的天数（end_date − start_date）。用于：住宿晚数（入住到离店）、出差天数（出发到返程，结果再 +1）、"
         "费用日期到提交日期是否超过 60 天。",
         CalcDaysBetweenArgs, calc_days_between),
]

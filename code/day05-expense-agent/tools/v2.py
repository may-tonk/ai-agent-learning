"""
v2：按 5 条工具设计原则重构后的工具集。

  原则 ①  按任务设计工具，不按底层接口：不再是"读文件"，而是 claims_get（取报销单）、policy_search（查条款）
  原则 ②  返回高信号信息、控制长度：claims_get 默认 concise；结果超长时明确告诉模型已截断
  原则 ③  报错可操作：每个错误都说明"哪里错 + 怎么改"，必要时给出可选值或示例
  原则 ④  名字和参数无歧义、有命名空间：claims_ / policy_ / calc_ / review_ 前缀，参数叫 claim_id 不叫 id
  原则 ⑤  用结构约束输入输出：Pydantic 参数模型 + strict 严格模式 + 最终结论走 review_submit 并做业务校验

（文章里还有一条"高风险操作单独对待"。这个 agent 只做审核、不打款，所有工具都是只读的，
 真正的打款动作在 agent 外面、由人确认后执行。这本身就是一种设计选择：让 agent 只拿到它需要的权限。）
"""
from tools import calculator, claims, policy
from tools.registry import Toolset
from tools.submit import TOOL as SUBMIT_TOOL
import config

TOOLSET = Toolset(
    name="v2",
    tools=[*claims.TOOLS, *policy.TOOLS, *calculator.TOOLS, SUBMIT_TOOL],
    strict=True,
    max_chars=config.MAX_TOOL_CHARS,
    announce_truncation=True,
)

DATA_ACCESS = "用 claims_get 读取报销单，用 policy_search 查询制度条款，用 calc_ 开头的工具做计算。"

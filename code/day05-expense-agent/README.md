# Day 5：报销审核 agent（工具设计 + 两家 tool use 协议）

业务场景：财务部每天收到大量报销单，人工逐笔对照制度审核。这个 agent 读取报销单、检索报销制度、用工具做所有计算，
给出每一笔费用的审核结果和整张单的结论（approve / partial / reject / needs_review），以固定结构提交，可以直接进入财务系统。

## 运行

在项目根目录 `E:\agent学习任务` 下，PyCharm Terminal 里看到 `(.venv)` 后执行。中文乱码时先执行 `$env:PYTHONIOENCODING="utf-8"`。

```powershell
# 0. 单元测试（不调用模型、不花钱，先确认代码没问题）
python -m unittest discover -s code/day05-expense-agent/tests -t code/day05-expense-agent

# 1. 审核一张报销单，看 agent 每一步在做什么
python code/day05-expense-agent/run_review.py --claim C002
python code/day05-expense-agent/run_review.py --claim C002 --tools v1
python code/day05-expense-agent/run_review.py --claim C002 --show-json    # 打印每一轮原始 JSON

# 2. 评测：v1（D3 原始版工具）和 v2（重构版工具）各跑 8 张报销单，对比准确率、工具调用次数、token
python code/day05-expense-agent/run_eval.py

# 3. 两家协议对比：同一任务分别走 OpenAI 协议和 Anthropic 协议，打印真实的请求/响应 JSON
python code/day05-expense-agent/compare_protocols.py
```

只需要 `.env` 里的 `DEEPSEEK_API_KEY`。运行记录写到 `logs/`（不进 Git）。

## 文件地图

```
config.py              配置：路径、模型、接口地址、上限（换模型/服务商只改这里或 .env）
data/
  policy.md            公司报销制度（P1~P6，条款带编号）
  claims/C001~C008     8 张报销单，含发票 OCR 原文、支付流水等真实系统里会有的"噪音字段"
  eval_cases.json      评测集：每张报销单的标准答案和考点
schemas/
  review.py            审核结果结构 ReviewResult（Pydantic），含金额加总、结论一致性校验
  strict.py            Pydantic schema → 严格模式 schema
tools/
  registry.py          Tool / Toolset：执行工具调用、错误处理、截断、翻译成两种协议格式
  v1_naive.py          v1：read_file + calculate（照搬 D3/Day 7 写法，作对照组）
  v2.py                v2：按 5 条原则组装的工具集
  claims.py            claims_get（concise / detailed）
  policy.py            policy_search（按关键词检索条款）
  calculator.py        calc_evaluate（安全求值，不用 eval）、calc_days_between
  submit.py            review_submit（最终答案工具）
prompts/system.md      system 提示词（与代码分离）
agent/
  loop.py              OpenAI 协议的 agent 循环（并行调用、提交校验、统计、对话记录）
  prompts.py           加载并填充提示词
run_review.py          入口：审核一张
run_eval.py            入口：评测 v1 vs v2
compare_protocols.py   入口：两家协议对比
tests/                 单元测试 + 假模型（不连网）
```

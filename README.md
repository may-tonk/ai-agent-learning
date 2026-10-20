# AI Agent 研究学习

从零开始学习并实现 AI agent：不依赖框架，手写 agent loop、工具调用（tool use）、JSON Schema 参数校验和工程化安全机制，再逐步过渡到框架、记忆、MCP 和完整项目。

学习路线见 [docs/AI-agent学习路线和项目分析 (1).md](docs/AI-agent学习路线和项目分析%20(1).md)：Day 0 加 3 周，共 22 天。

## 目录结构

```
docs/                      学习路线文档
code/
  day07-minimal-agent/     最小 agent：约 50 行核心代码，3 个文件工具
  day07-order-agent/       综合练习：电商客服 agent
  day05-expense-agent/     Day 5：报销审核 agent（工具设计原则、评测、两家 tool use 协议对比）
requirements.txt           Python 依赖
.env.example               环境变量模板（真实的 .env 不提交）
```

## 已完成的练习

### day07-minimal-agent：最小 agent

用最少的代码说明 agent 的骨架：LLM + 循环 + 工具 + 上下文（messages）。任务是找出 `demo/` 目录里所有的 TODO 注释，并汇总成一份报告。

- `agent_deepseek.py`：DeepSeek 版本（OpenAI 兼容接口）
- `agent.py`：Anthropic Claude 版本

### day07-order-agent：电商客服 agent

把 JSON Schema、tool use、agent loop 和工程机制放进一个真实业务场景。数据是本地的 10 个模拟订单。

| 机制 | 说明 |
| --- | --- |
| JSON Schema | 4 个工具都有完整的参数 schema（enum、pattern、format、exclusiveMinimum、additionalProperties），执行前用 `jsonschema` 校验 |
| 五层拦截 | 工具名 → JSON 解析 → Schema 校验 → 执行（业务规则）→ 输出截断；任何一层出错，都把原因作为工具结果交还给模型 |
| 业务规则写在代码里 | 退款条件（已签收、7 天内、金额上限）由代码判断，模型无法绕过 |
| 人工确认 | 退款这类写操作，执行前在终端等待人工输入 y/n（human-in-the-loop） |
| 多轮对话 | `messages` 在整个会话中保留；支持 `/history`、`/reset`、`/exit` |
| 可观察性 | 每一步打印 `prompt_tokens`，完整运行记录保存到 `logs/` |
| 测试场景 | `query`、`refund`、`edge`（格式错误、超额退款）、`injection`（订单备注中的提示词注入） |

### day05-expense-agent：报销审核 agent

财务报销审核场景：读取报销单、检索带条款编号的报销制度、所有金额用工具计算，逐笔给出通过 / 核减 / 拒绝 / 转人工，并以固定结构提交结论。

| 内容 | 说明 |
| --- | --- |
| 工具设计对照 | v1 照搬 D3/Day 7 写法（`read_file` + `calculate`）；v2 按 5 条原则重构（`claims_get` / `policy_search` / `calc_*` / `review_submit`） |
| 评测 | 8 张报销单配人工标准答案，`run_eval.py` 对比 v1、v2 的准确率、工具调用次数和 token |
| 结构化输出 | 最终结论走 `review_submit` 工具（strict 模式 + Pydantic 业务一致性校验，不通过就把错误交还模型重试） |
| 上下文工程 | 每轮打印 token；报销单含发票 OCR 等噪音字段，v2 默认只返回审核需要的字段 |
| 协议对比 | `compare_protocols.py` 用同一任务分别走 OpenAI 协议和 Anthropic 协议（DeepSeek 两种兼容接口），打印真实 JSON |
| 测试 | 21 个单元测试，用假模型验证循环逻辑，不连网 |

详细说明见 [code/day05-expense-agent/README.md](code/day05-expense-agent/README.md)。

## 运行

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env    # 填入 DEEPSEEK_API_KEY

python code/day07-minimal-agent/agent_deepseek.py
python code/day07-order-agent/agent.py                      # 交互模式
python code/day07-order-agent/agent.py --scenario refund    # 场景模式

python -m unittest discover -s code/day05-expense-agent/tests -t code/day05-expense-agent
python code/day05-expense-agent/run_review.py --claim C002
python code/day05-expense-agent/run_eval.py
python code/day05-expense-agent/compare_protocols.py
```

## 进度

- [x] Day 7：最小 agent（DeepSeek 和 Claude 两个版本）
- [x] Day 7 综合练习：电商客服 agent（JSON Schema 校验、业务规则、人工确认、提示词注入测试）
- [x] Day 5：报销审核 agent（工具设计原则、评测、结构化输出、两家协议对比）
- [ ] 第 2 周：阅读主流 agent 框架源码，建立评估基线
- [ ] 第 3 周：记忆、MCP、链上工具与安全、毕业项目

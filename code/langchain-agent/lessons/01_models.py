"""
【模块一：Models】模型体检脚本

要回答的问题：
    模型对象是怎么来的？参数改了输出怎么变？一次调用花了多少 token、为什么越聊越贵？
    invoke / stream / batch 有什么区别？报错时怎么判断是哪一类问题？

需要：.env 里配置好 DEEPSEEK_API_KEY（每节都会真实调用 DeepSeek，全部跑完约花几分钱）
运行：python lessons/01_models.py            全部
      python lessons/01_models.py --part 4   只看第 4 节
"""
import _common  # noqa: F401  必须第一个导入：把项目根目录加进 sys.path
from _common import note, run_parts, title

import time

from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.exceptions import ModelError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent.schemas import ServiceSummary
from model.factory import build_chat_model, get_chat_model
from utils.config_handler import model_conf


def part1_create():
    title("1. 模型对象是怎么创建出来的")
    model = get_chat_model()
    print("配置文件 config/model.yml 的 chat 段：", model_conf["chat"])
    print("init_chat_model 返回的类：", type(model).__name__, "来自", type(model).__module__)
    print("模型名：", model.model_name, "｜temperature：", model.temperature, "｜max_tokens：", model.max_tokens)
    note("init_chat_model 按 provider=deepseek 找到 langchain-deepseek 包里的 ChatDeepSeek。")
    note("ChatDeepSeek 继承自 BaseChatModel，所以和 OpenAI、通义等模型对象的用法完全一样。")


def part2_invoke():
    title("2. invoke：一次完整调用，返回的是 AIMessage，不是字符串")
    model = get_chat_model()
    response = model.invoke(
        [
            SystemMessage("你是扫地机器人售后客服，回答不超过 50 字。"),
            HumanMessage("扫地机器人边刷多久换一次？"),
        ]
    )
    print("返回类型：", type(response).__name__)
    print("response.text：", response.text)
    print("response.usage_metadata：", response.usage_metadata)
    meta = response.response_metadata
    print("response_metadata 里的关键字段：")
    print("   model_name    =", meta.get("model_name"))
    print("   finish_reason =", meta.get("finish_reason"), " ← stop 表示模型自己说完了")
    note("input_tokens 包括系统提示词 + 用户问题，不只是你看到的那一句话。")


def part3_temperature():
    title("3. temperature：同一个问题问 3 次，看输出稳不稳定")
    question = "给一款扫拖一体机器人想一句广告语，10 个字以内，只输出广告语。"
    for temp in (0.0, 1.5):
        model = build_chat_model(temperature=temp)  # 临时覆盖配置里的 temperature
        answers = [model.invoke(question).text.strip() for _ in range(3)]
        print(f"temperature={temp}：")
        for a in answers:
            print("   ", a)
    note("temperature 低：每次几乎一样，适合客服、分类、数据抽取。")
    note("temperature 高：每次不一样，适合起名字、写文案。它控制的是随机性，不是准确率。")


def part4_max_tokens():
    title("4. max_tokens 太小：回答被截断")
    model = build_chat_model(max_tokens=30)
    response = model.invoke("详细介绍扫地机器人激光导航和视觉导航的区别。")
    print("回答：", response.text)
    print("finish_reason：", response.response_metadata.get("finish_reason"), " ← length 表示被 max_tokens 截断")
    print("output_tokens：", response.usage_metadata["output_tokens"])
    note("如果 agent 生成的 JSON 或报告总是不完整，先看 finish_reason 是不是 length。")
    note("max_tokens 只限制「输出」长度；能塞多少历史消息由模型的上下文窗口决定，是另一回事。")


def part5_stream():
    title("5. stream：边生成边返回（网页上的打字机效果）")
    model = get_chat_model()
    full = None
    count = 0
    start = time.perf_counter()
    first_at = None
    for chunk in model.stream("用三句话说明扫地机器人为什么会迷路。"):
        count += 1
        if first_at is None:
            first_at = time.perf_counter() - start
        print(chunk.text, end="|", flush=True)  # 用 | 隔开，看清每一块有多大
        # AIMessageChunk 之间可以用 + 合并：文本拼接，token 用量等元数据也一起合并
        full = chunk if full is None else full + chunk
    total = time.perf_counter() - start
    print(f"\n共收到 {count} 块；第一块用时 {first_at:.2f}s，全部完成用时 {total:.2f}s")
    print("合并后的类型：", type(full).__name__, "｜usage：", full.usage_metadata)
    note("stream 不会让总时间变短，但用户在第一块到达时就能看到内容，体验好很多。")


def part6_batch():
    title("6. batch：一次并发处理多条输入")
    model = get_chat_model()
    questions = [
        "用户说：机器人充不进电。这属于哪类问题？只回答：故障/使用/物流/其他",
        "用户说：我的订单到哪了。这属于哪类问题？只回答：故障/使用/物流/其他",
        "用户说：拖布多久洗一次。这属于哪类问题？只回答：故障/使用/物流/其他",
    ]
    start = time.perf_counter()
    results = model.batch(questions, config={"max_concurrency": 3})
    print(f"batch 3 条用时 {time.perf_counter() - start:.2f}s")
    for q, r in zip(questions, results):
        print("   ", q[4:16], "→", r.text.strip())
    note("batch 内部是并发请求，适合离线批量任务（比如给一天的工单分类）。max_concurrency 防止并发太高被限流。")


def part7_token_growth():
    title("7. 为什么对话越长越贵：每次调用都要把全部历史重新发一遍")
    model = get_chat_model()
    history = [SystemMessage("你是扫地机器人售后客服，每次回答不超过 30 字。")]
    turns = ["我的机器人总是迷路", "重新建图要多久", "建图时人要不要离开房间", "那家里有宠物怎么办"]
    with get_usage_metadata_callback() as cb:  # 统计 with 块里所有模型调用的 token
        for i, text in enumerate(turns, start=1):
            history.append(HumanMessage(text))
            reply = model.invoke(history)
            history.append(reply)
            print(f"第 {i} 轮：输入 {reply.usage_metadata['input_tokens']:>4} token，输出 {reply.usage_metadata['output_tokens']:>3} token")
    print("4 轮合计：", cb.usage_metadata)
    note("模型没有记忆。第 4 轮的输入 = 系统提示词 + 前 3 轮全部问答 + 新问题，所以输入 token 一直涨。")
    note("这就是 agent 要做「对话摘要」（SummarizationMiddleware）的原因：见 agent/agent.py。")


def part8_profile():
    title("8. model.profile：查看模型能力（工具调用、图片输入、上下文长度）")
    model = get_chat_model()
    print("profile：", model.profile)
    note("profile 是 LangChain 内置的模型能力表（Beta），没登记的模型（比如 deepseek-chat）就是 None 或不完整。")
    note("所以选模型时不能只看 profile，要用一次真实的小测试确认，比如下一节的结构化输出。")


def part9_structured():
    title("9. with_structured_output：让模型按 Pydantic 结构返回")
    model = build_chat_model("summary")
    structured = model.with_structured_output(ServiceSummary)
    transcript = (
        "用户：我上周买的 X1 Pro 拖地一直漏水，订单 SO20260312，太烦了！\n"
        "客服调用工具：check_warranty({'order_id': 'SO20260312', 'fault_category': '拖地漏水'})\n"
        "工具结果：在保修期内\n"
        "客服：您的机器在保修期内，已为您提交维修工单 TK202610230001，免费维修。\n"
        "用户：好的，尽快。"
    )
    result = structured.invoke(f"根据下面的对话填写服务小结：\n{transcript}")
    print("返回类型：", type(result).__name__)
    print(result.model_dump_json(indent=2))
    note("DeepSeek 的 with_structured_output 默认用 function_calling：把 ServiceSummary 当成一个工具让模型「调用」，")
    note("再把参数解析成 Pydantic 对象。所以模型必须支持工具调用才能用这个功能。")


def part10_errors():
    title("10. 报错分类：每种错误该怎么处理")
    cases = [
        ("错误的 API key", build_chat_model(api_key="sk-wrong-key", max_retries=0)),
        ("不存在的模型名", build_chat_model(model="deepseek-not-exist", max_retries=0)),
        ("超时时间设成 0.01 秒", build_chat_model(timeout=0.01, max_retries=0)),
    ]
    for label, model in cases:
        try:
            model.invoke("你好")
            print(f"{label}：居然成功了")
        except ModelError as e:
            # LangChain 1.x 把各家模型的错误统一成这几类，判断时不用关心是哪家模型
            print(f"{label}：{type(e).__name__}")
            print(f"    属于标准类型：{[c.__name__ for c in type(e).__mro__ if c.__module__ == 'langchain_core.exceptions']}")
            print(f"    is_retryable = {e.is_retryable}")
    note("is_retryable=False（认证失败、模型不存在）：改配置，重试多少次都没用。")
    note("is_retryable=True（超时、限流、服务端 5xx）：可以退避后重试，max_retries 就是干这个的。")
    note("main.py 里就是按这几类异常分别给出提示的。")


if __name__ == "__main__":
    run_parts(
        {
            1: part1_create,
            2: part2_invoke,
            3: part3_temperature,
            4: part4_max_tokens,
            5: part5_stream,
            6: part6_batch,
            7: part7_token_growth,
            8: part8_profile,
            9: part9_structured,
            10: part10_errors,
        },
        "Models 模块练习",
    )

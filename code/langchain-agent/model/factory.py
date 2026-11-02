"""
模型工厂：整个项目只在这里创建模型对象

【Models 模块的核心】
1. init_chat_model：LangChain 的统一入口。传 provider + model 名，它去找对应的集成包
   （deepseek → langchain-deepseek 的 ChatDeepSeek），返回的对象都有同样的方法：
   invoke / stream / batch / bind_tools / with_structured_output。
   换模型厂商时业务代码不用改，只改 config/model.yml。
2. 参数（temperature / max_tokens / timeout / max_retries）全部来自配置文件。

和实验6 的区别：实验6 在模块导入时就创建了 chat_model 和 embed_model（全局变量），
导致「只想测一下聊天模型」也必须配好向量模型的 key。这里改成「用到时才创建」（懒加载），
并用 lru_cache 保证同一个模型只创建一次。

【在整体流程里的位置】main.py → agent/agent.py（build_agent 时要模型）→ 本文件 → DeepSeek / 百炼 API
谁调用它：
    agent/agent.py           build_agent：get_chat_model()（主模型）、build_chat_model("summary"/"fallback")
    services/summary_service build_chat_model("summary")：/summary 会话小结
    services/kb_service      get_embeddings()：第一次检索知识库时
    services/rerank_service  get_reranker()：检索第 2 步，对召回的候选资料重新打分排序
    lessons/01_models.py     build_chat_model(temperature=...)：对比不同参数的效果
注意：创建模型对象不会发网络请求，只有调用 invoke / stream 时才真正请求 API、才花钱。
"""
import utils.env_loader  # noqa: F401  导入即加载 .env（DEEPSEEK_API_KEY 等），必须放在最前面

import os
from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from utils.config_handler import model_conf


def build_chat_model(section: str = "chat", **overrides) -> BaseChatModel:
    """
    按 config/model.yml 里的某一段创建聊天模型。每调用一次就新建一个对象（不缓存）。

    section：用哪一段配置（chat / fallback / summary）
    overrides：临时覆盖参数，比如 lessons 里想对比 temperature=0 和 1.3 的效果，
               就传 build_chat_model(temperature=1.3)，不用改配置文件
    返回：BaseChatModel 的子类对象（这里是 ChatDeepSeek）
    """
    conf = dict(model_conf[section])        # 复制一份，避免改到全局配置
    conf.update(overrides)

    provider = conf.pop("provider")
    model = conf.pop("model")

    # init_chat_model 的参数：
    #   model           模型名，如 "deepseek-chat"
    #   model_provider  厂商名，决定加载哪个集成包、哪个模型类（deepseek → ChatDeepSeek）
    #   **conf          其余键（temperature、max_tokens、timeout、max_retries）原样传给模型类的构造函数
    # 例如最终相当于：ChatDeepSeek(model="deepseek-chat", temperature=0.3, max_tokens=1024, ...)
    # API key 不用传：ChatDeepSeek 会自己从环境变量 DEEPSEEK_API_KEY 读（由 env_loader 从 .env 加载）
    return init_chat_model(model=model, model_provider=provider, **conf)


@lru_cache
def get_chat_model() -> BaseChatModel:
    """
    主聊天模型（agent 用的那个），整个程序共用一个对象。
    lru_cache：第一次调用时创建，之后直接返回同一个对象（模型对象里有 HTTP 连接池，复用更快）。
    谁调用：agent/agent.py 的 build_agent（没传 model 参数时）
    """
    return build_chat_model("chat")


@lru_cache
def get_embeddings() -> Embeddings:
    """
    向量模型：只在检索知识库时才会被调用。
    必须和实验6 建库时的模型、维度完全一致（向量空间不同，检索结果就是乱的）。

    根据 config/model.yml 的 embedding.api 选择实现：
        multimodal → 我们自己写的 DashScopeMultiModalEmbeddings（qwen3-vl-embedding 必须走这个）
        text       → LangChain 自带的 DashScopeEmbeddings（text-embedding-v3 这类纯文本模型）
    两者都实现了 Embeddings 接口（embed_documents / embed_query），Chroma 不关心具体是哪个。
    谁调用：services/kb_service.py 的 _get_vector_store
    """
    conf = model_conf["embedding"]

    if conf.get("api", "text") == "multimodal":
        # 放在函数里导入：没用到知识库时，不需要装 dashscope、也不需要 DASHSCOPE_API_KEY
        from model.multimodal_embeddings import DashScopeMultiModalEmbeddings

        return DashScopeMultiModalEmbeddings(
            model=conf["model"],
            dimension=conf.get("dimension", 1024),
            batch_size=conf.get("batch_size", 10),
        )

    # 文本向量接口
    from langchain_community.embeddings import DashScopeEmbeddings

    return DashScopeEmbeddings(model=conf["model"])


@lru_cache
def get_reranker():
    """
    重排模型：检索的第 2 步（精排），整个程序共用一个对象。

    功能：给「问题 + 每条候选资料」打相关性分数（0 ~ 1，越大越相关），用来给向量检索召回的结果重新排序
    使用 LangChain 自带的 DashScopeRerank（langchain_community），调用阿里云百炼的文本重排接口
    参数（来自 config/model.yml 的 rerank 段）：
        model              重排模型名，当前 gte-rerank-v2
        dashscope_api_key  百炼的 key，和向量模型共用 .env 里的 DASHSCOPE_API_KEY
    返回：DashScopeRerank 对象，主要用它的 .rerank(documents, query, top_n) 方法：
          返回 [{"index": 候选的原始位置, "relevance_score": 分数}, ...]，已经按分数从高到低排好
    谁调用：services/rerank_service.py 的 rerank()
    注意：创建对象不会发网络请求，调用 .rerank() 时才真正请求百炼、才花钱
    """
    conf = model_conf["rerank"]

    # 放在函数里导入：关掉重排（config/chroma.yml 的 rerank.enabled: false）时不需要加载它
    from langchain_community.document_compressors import DashScopeRerank

    reranker = DashScopeRerank(
        model=conf["model"],
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
    )
    # ！注意：langchain_community 的 DashScopeRerank 有 bug（实测，0.4.2 版）：
    #   它的 validate_environment 在创建对象时把 model 强制改成 "gte-rerank"（旧版 v1 模型），不管我们传的是什么。
    #   结果是实际请求的是 gte-rerank，账号没开通这个模型时百炼返回 403 AccessDenied，
    #   而 DashScopeRerank 不检查状态码，最后表现为看不懂的 AttributeError: 'NoneType' object has no attribute 'results'。
    #   所以创建完再把 model 改回配置里的值（对象允许赋值，改完 reranker.model 就是 gte-rerank-v2）
    reranker.model = conf["model"]
    return reranker

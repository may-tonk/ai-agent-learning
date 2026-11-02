"""
百炼多模态向量模型（如 qwen3-vl-embedding）的 LangChain 适配

为什么要自己写：LangChain 自带的 DashScopeEmbeddings 走的是百炼「文本向量」接口（TextEmbedding），
而 qwen3-vl-embedding 属于「多模态向量」，要走另一个接口（MultiModalEmbedding），直接换模型名会报错。
做法：继承 LangChain 的 Embeddings 接口，实现 embed_documents / embed_query 两个方法，
这样 Chroma、检索器等上层代码完全不用改 —— 这就是"面向接口编程"的好处。

【在整体流程里的位置】
services/kb_service.search → Chroma.similarity_search_with_score → 本类的 embed_query（把问题变成向量）
谁创建它：model/factory.py 的 get_embeddings（config/model.yml 里 embedding.api = multimodal 时）
"""
import os

import dashscope
from langchain_core.embeddings import Embeddings


class DashScopeMultiModalEmbeddings(Embeddings):
    """
    把文本变成向量（一串浮点数）。语义相近的文本，向量之间的距离也近，向量检索就是靠这个。
    """

    def __init__(self, model: str, dimension: int = 1024, batch_size: int = 10):
        """
        model：百炼模型名，如 "qwen3-vl-embedding"
        dimension：输出向量的维度，必须和建库时一致（见 config/model.yml）
        batch_size：一次请求最多送几段文本
        异常：.env 里没有 DASHSCOPE_API_KEY 时直接报错（早发现，好过检索时才报一个看不懂的 401）
        """
        self.model = model
        self.dimension = dimension        # 向量维度；该模型默认 2560，可选 256~2048，建库后不要改
        self.batch_size = batch_size      # 接口一次最多 20 个内容元素，留余量
        self.api_key = os.getenv("DASHSCOPE_API_KEY")
        if not self.api_key:
            raise ValueError("缺少 DASHSCOPE_API_KEY，请在 .env 里配置")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """
        真正调用百炼接口的地方：按 batch_size 分批请求，再按顺序拼起来。
        texts：要向量化的文本列表
        返回：和 texts 一一对应的向量列表，每个向量长度 = self.dimension
        """
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            # dashscope.MultiModalEmbedding.call 的参数：
            #   api_key  百炼的 key
            #   model    模型名
            #   input    内容列表，每个元素是 {"text": ...}（多模态接口也可以传 {"image": url}，这里只用文本）
            #   dimension 输出维度
            resp = dashscope.MultiModalEmbedding.call(
                api_key=self.api_key,
                model=self.model,
                input=[{"text": t} for t in batch],
                # 注意：维度要作为 dimension= 参数直接传；写成 parameters={"dimension": ...} 会被 SDK 忽略，
                # 返回默认的 2560 维（实测踩过的坑）
                dimension=self.dimension,
            )
            if resp.status_code != 200:
                raise RuntimeError(f"百炼向量化失败：{resp.code} {resp.message}")
            # 按 index 排序，保证返回的向量和输入文本一一对应
            items = sorted(resp.output["embeddings"], key=lambda e: e.get("index", 0))
            vectors.extend(item["embedding"] for item in items)
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embeddings 接口要求的方法之一。建库时调用：一批文本块 → 一批向量（本项目只读库，基本用不到）"""
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embeddings 接口要求的方法之一。检索时调用：用户问题 → 一个向量"""
        return self._embed([text])[0]

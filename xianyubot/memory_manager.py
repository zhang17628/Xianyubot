# memory_manager.py
import os
import asyncio
import threading
import numpy as np
from datetime import datetime
from loguru import logger

from lightrag import LightRAG, QueryParam
from lightrag.utils import EmbeddingFunc
from openai import AsyncOpenAI, OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", OPENAI_API_KEY)
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "")  # 留空则用本地模型
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")


_SentenceTransformer = None

_local_model = None
_local_model_lock = threading.Lock()


def _get_local_model():
    """懒加载本地 Embedding 模型"""
    global _local_model
    if _local_model is not None:
        return _local_model

    with _local_model_lock:
        # 双重检查
        if _local_model is not None:
            return _local_model

        if _SentenceTransformer is None:
            raise RuntimeError(
                "本地 Embedding 需要安装 sentence-transformers:\n"
                "  pip install sentence-transformers"
            )

        model_name = "BAAI/bge-small-zh-v1.5"
        logger.info(f"📥 正在下载/加载本地 Embedding 模型: {model_name}")
        _local_model = _SentenceTransformer(model_name)
        logger.info(f"✅ 本地 Embedding 模型加载完成，维度: {_local_model.get_sentence_embedding_dimension()}")
        return _local_model


def _get_embedding_dim() -> int:
    """根据配置确定 Embedding 维度"""
    if not EMBEDDING_BASE_URL:
        # 本地模型
        model = _get_local_model()
        return model.get_sentence_embedding_dimension()

    # 远程 API 模型维度映射
    dim_map = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
        "BAAI/bge-m3": 1024,
        "BAAI/bge-large-zh-v1.5": 1024,
        "BAAI/bge-small-zh-v1.5": 512,
    }
    return dim_map.get(EMBEDDING_MODEL, 1024)


# ========================================
# LLM 函数
# ========================================
def _create_llm_func():
    _client = None

    async def llm_func(prompt, system_prompt=None, history_messages=None, **kwargs) -> str:
        nonlocal _client
        if _client is None:
            _client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

        if history_messages is None:
            history_messages = []

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history_messages)
        messages.append({"role": "user", "content": prompt})

        try:
            response = await _client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=kwargs.get("temperature", 0.1),
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"LightRAG LLM 调用失败: {e}")
            return ""

    return llm_func


# ========================================
# Embedding 函数
# ========================================
def _create_embedding_func():
    """根据配置自动选择远程 API 或本地模型"""

    if EMBEDDING_BASE_URL:
        # ========== 远程 API 模式 ==========
        logger.info(f"🌐 Embedding 使用远程 API: {EMBEDDING_BASE_URL}, model={EMBEDDING_MODEL}")
        _client = None

        async def embedding_func(texts: list[str], **kwargs) -> np.ndarray:
            nonlocal _client
            if _client is None:
                _client = AsyncOpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL)

            dim = _get_embedding_dim()

            # 过滤空字符串
            cleaned_texts = []
            original_indices = []
            for i, t in enumerate(texts):
                stripped = t.strip() if t else ""
                if stripped:
                    cleaned_texts.append(stripped)
                    original_indices.append(i)

            if not cleaned_texts:
                return np.zeros((len(texts), dim))

            try:
                response = await _client.embeddings.create(
                    model=EMBEDDING_MODEL,
                    input=cleaned_texts,
                    encoding_format="float",
                )

                if not response.data:
                    logger.error(f"❌ Embedding API 返回空 data")
                    return np.zeros((len(texts), dim))

                # 映射回原始位置
                actual_dim = len(response.data[0].embedding)
                result = np.zeros((len(texts), actual_dim))
                for idx, emb_data in enumerate(response.data):
                    orig_idx = original_indices[idx]
                    result[orig_idx] = emb_data.embedding

                return result

            except Exception as e:
                logger.error(f"❌ Embedding API 调用失败: {e}")
                return np.zeros((len(texts), dim))

        return embedding_func

    else:
        # ========== 本地模型模式 ==========
        logger.info(f"💻 Embedding 使用本地模型（无需 API）")

        async def embedding_func(texts: list[str], **kwargs) -> np.ndarray:
            model = _get_local_model()
            dim = model.get_sentence_embedding_dimension()

            # 过滤空字符串
            cleaned_texts = [t.strip() if t else "空" for t in texts]

            try:
                loop = asyncio.get_event_loop()
                embeddings = await loop.run_in_executor(
                    None, lambda: model.encode(cleaned_texts, normalize_embeddings=True)
                )
                return np.array(embeddings)
            except Exception as e:
                logger.error(f"❌ 本地 Embedding 计算失败: {e}")
                return np.zeros((len(texts), dim))

        return embedding_func


# ========================================
# 长期记忆类
# ========================================
class LongTermMemory:
    def __init__(self, working_dir="data/lightrag_memory"):
        self.working_dir = working_dir
        os.makedirs(working_dir, exist_ok=True)
        self.rag = None
        self._initialized = False

    async def _ensure_initialized(self):
        if self._initialized:
            return

        try:
            emb_dim = _get_embedding_dim()
            emb_func = _create_embedding_func()
            llm_func = _create_llm_func()

            logger.info(f"🔧 初始化 LightRAG: embedding_dim={emb_dim}")

            self.rag = LightRAG(
                working_dir=self.working_dir,
                llm_model_func=llm_func,
                embedding_func=EmbeddingFunc(
                    embedding_dim=emb_dim,
                    max_token_size=8192,
                    func=emb_func,
                ),
            )
            await self.rag.initialize_storages()

            self._initialized = True
            logger.info(f"✅ LightRAG 长期记忆初始化成功")
        except Exception as e:
            logger.error(f"❌ LightRAG 初始化失败: {e}")
            raise

    async def add_conversation(
        self, chat_id: str, user_id: str, item_id: str, role: str, content: str,
        image_description: str = None, item_info: dict = None,
    ):
        await self._ensure_initialized()
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            doc_parts = [
                f"【对话记录】",
                f"时间: {timestamp}",
                f"会话ID: {chat_id}",
                f"用户ID: {user_id}",
                f"商品ID: {item_id}",
                f"角色: {'买家' if role == 'user' else '卖家(AI客服)'}",
                f"消息内容: {content}",
            ]
            if image_description:
                doc_parts.append(f"图片描述: {image_description}")
            if item_info:
                title = item_info.get("title", "")
                price = item_info.get("soldPrice", "")
                desc = item_info.get("desc", "")
                if title: doc_parts.append(f"相关商品: {title}")
                if price: doc_parts.append(f"商品价格: {price}元")
                if desc: doc_parts.append(f"商品描述: {desc[:200]}")
            document = "\n".join(doc_parts)

            await self.rag.ainsert(document)
            logger.debug(f"💾 长期记忆已存储: chat={chat_id}, role={role}, content={content[:50]}...")
        except Exception as e:
            logger.error(f"❌ 长期记忆存储失败: {e}")

    async def search_memory(
        self, query: str, chat_id: str = None, mode: str = "hybrid", top_k: int = 5,
    ) -> str:
        await self._ensure_initialized()
        try:
            search_query = f"会话{chat_id}的历史记录: {query}" if chat_id else query
            result = await self.rag.aquery(
                search_query, param=QueryParam(mode=mode, top_k=top_k)
            )
            if (
                result and result.strip()
                and "I am sorry" not in result
                and "[no-context]" not in result
            ):
                logger.info(f"🔍 长期记忆检索到结果: {result[:100]}...")
                return result
            logger.debug("🔍 长期记忆未检索到相关结果")
            return ""
        except Exception as e:
            logger.error(f"❌ 长期记忆检索失败: {e}")
            return ""

    async def describe_image(self, image_url: str, context: str = "") -> str:
        try:
            sync_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            messages = [
                {"role": "system", "content": "请用简洁中文描述图片，关注外观、品牌、成色等，100字内。"},
                {"role": "user", "content": [
                    {"type": "text", "text": "请描述图片。"},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ]},
            ]
            response = sync_client.chat.completions.create(
                model=LLM_MODEL, messages=messages, max_tokens=200
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"❌ 图片描述失败: {e}")
            return "图片描述生成失败"


class LongTermMemorySync:
    def __init__(self, working_dir="data/lightrag_memory"):
        self.working_dir = working_dir
        self._loop = asyncio.new_event_loop()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        future = asyncio.run_coroutine_threadsafe(self._init_memory(), self._loop)
        self._async_memory = future.result(timeout=60)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _init_memory(self):
        return LongTermMemory(working_dir=self.working_dir)

    def _run_async(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=180)

    def add_conversation(self, chat_id, user_id, item_id, role, content,
                         image_description=None, item_info=None):
        try:
            self._run_async(
                self._async_memory.add_conversation(
                    chat_id, user_id, item_id, role, content,
                    image_description, item_info,
                )
            )
        except Exception as e:
            logger.error(f"同步存入长期记忆失败: {e}")

    def search_memory(self, query, chat_id=None, mode="hybrid", top_k=5) -> str:
        try:
            return self._run_async(
                self._async_memory.search_memory(query, chat_id, mode, top_k)
            )
        except Exception as e:
            logger.error(f"同步检索长期记忆失败: {e}")
            return ""

    def describe_image(self, image_url, context="") -> str:
        try:
            return self._run_async(
                self._async_memory.describe_image(image_url, context)
            )
        except Exception as e:
            logger.error(f"同步描述出错")

"""应用级依赖容器。

集中创建并复用重对象（QwenClient / MemoryManager / 记忆抽取器等），
通过 FastAPI ``Depends`` 注入到路由，替代模块级全局单例：

- 进程内单例（``lru_cache``），避免每次请求重复构造；
- 便于测试替换与配置统一管理。
"""
from functools import lru_cache

from app.llm.qwen_client import QwenClient
from app.memory.conversation_summarizer import ConversationSummarizer
from app.memory.memory_extractor import MemoryExtractor
from app.memory.memory_manager import MemoryManager
from app.memoir.story_extractor import StoryExtractor
from app.rag.knowledge_base import KnowledgeBase


@lru_cache(maxsize=1)
def get_qwen_client() -> QwenClient:
    return QwenClient()


@lru_cache(maxsize=1)
def get_memory_manager() -> MemoryManager:
    return MemoryManager()


@lru_cache(maxsize=1)
def get_memory_extractor() -> MemoryExtractor:
    return MemoryExtractor(get_qwen_client())


@lru_cache(maxsize=1)
def get_conversation_summarizer() -> ConversationSummarizer:
    return ConversationSummarizer(get_qwen_client())


@lru_cache(maxsize=1)
def get_story_extractor() -> StoryExtractor:
    """生平故事提取器（回忆录管线，与事实记忆提取器相互独立）。"""
    return StoryExtractor(get_qwen_client())


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    """进程内复用 RAG 服务，Embedding 客户端按需初始化。"""
    return KnowledgeBase(embed_fn=get_qwen_client().embed)

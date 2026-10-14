"""对话摘要生成器。

用于对话压缩和记忆整合：调用 Qwen 将多轮对话或相似记忆合并为简短摘要。
"""
import logging
from typing import List, Tuple

from app.llm.qwen_client import QwenClient

logger = logging.getLogger(__name__)

# 对话摘要 Prompt
SUMMARIZE_SYSTEM_PROMPT = """你是老人陪伴系统的对话压缩模块。请将以下对话历史压缩为一段简短摘要（2-3句话），保留：
1. 主要话题
2. 老人的情绪状态
3. 提到的关键人物或事件

摘要要求：
- 不超过 100 字
- 用第三人称描述
- 保留关键信息，去除寒暄和重复
- 语言简洁自然

摘要："""

# 记忆合并 Prompt
MERGE_SYSTEM_PROMPT = """你是记忆管理模块。以下多条记忆语义高度相似，请合并为一条简洁的陈述，保留最重要的信息：

记忆列表：
{memories}

合并要求：
- 合并为一条不超过 30 字的陈述
- 保留最核心、最新的信息
- 去除重复和冗余
- 语言自然流畅

合并后的记忆："""


class ConversationSummarizer:
    """对话摘要生成器。"""

    def __init__(self, client: QwenClient) -> None:
        self.client = client

    async def summarize(self, turns: List[Tuple[str, str]]) -> str:
        """将多轮对话压缩为摘要。

        Args:
            turns: [(role, content), ...] 格式的对话历史

        Returns:
            摘要文本
        """
        if not turns:
            return ""

        # 格式化对话历史
        conversation_text = "\n".join(
            f"{'老人' if role == 'user' else 'AI'}：{content}"
            for role, content in turns
        )

        messages = [
            {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": conversation_text},
        ]

        try:
            summary = await self.client.chat(messages, temperature=0.3, max_tokens=150)
            logger.info("生成对话摘要：%s", summary[:50])
            return summary.strip()
        except Exception as e:
            logger.exception("生成对话摘要失败：%s", e)
            return ""

    async def merge_memories(self, memories: List[str]) -> str:
        """将多条相似记忆合并为一条。

        Args:
            memories: 记忆文本列表

        Returns:
            合并后的记忆文本
        """
        if not memories:
            return ""

        if len(memories) == 1:
            return memories[0]

        memories_text = "\n".join(f"- {m}" for m in memories)
        prompt = MERGE_SYSTEM_PROMPT.format(memories=memories_text)

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请合并以上记忆"},
        ]

        try:
            merged = await self.client.chat(messages, temperature=0.3, max_tokens=100)
            logger.info("合并记忆：%s", merged[:50])
            return merged.strip()
        except Exception as e:
            logger.exception("合并记忆失败：%s", e)
            # 失败时返回第一条
            return memories[0]

"""每日记忆整合任务。

每天凌晨 2:00 执行，合并相似记忆，减少冗余。
"""
import logging
from datetime import datetime

from app.db import get_conn
from app.memory.long_memory import LongMemoryStore
from app.memory.conversation_summarizer import ConversationSummarizer
from app.llm.qwen_client import QwenClient

logger = logging.getLogger(__name__)

# 相似度阈值：超过此值的记忆会被合并
CONSOLIDATION_THRESHOLD = 0.85


async def memory_consolidation_job():
    """每日记忆整合：合并相似记忆。"""
    logger.info("开始每日记忆整合任务")
    
    long_memory = LongMemoryStore()
    summarizer = ConversationSummarizer(QwenClient())
    
    # 获取所有有记忆的用户
    with get_conn() as conn:
        user_ids = conn.execute(
            "SELECT DISTINCT user_id FROM memories"
        ).fetchall()
    
    consolidated_count = 0
    
    for row in user_ids:
        user_id = row["user_id"]
        
        # 获取该用户的所有记忆
        memories = long_memory.list_all(user_id)
        if len(memories) < 2:
            continue
        
        # 找出需要合并的记忆组
        merged_groups = await _find_merge_groups(memories, long_memory)
        
        for group in merged_groups:
            if len(group) < 2:
                continue
            
            # 保留重要性最高的记忆
            group.sort(key=lambda m: m["importance"], reverse=True)
            primary = group[0]
            to_merge = group[1:]
            
            # 合并内容
            contents = [m["content"] for m in group]
            merged_content = await summarizer.merge_memories(contents)
            
            if merged_content and merged_content != primary["content"]:
                # 更新主记忆
                with get_conn() as conn:
                    conn.execute(
                        "UPDATE memories SET content = ? WHERE id = ?",
                        (merged_content, primary["id"])
                    )
                
                # 删除其他记忆
                for m in to_merge:
                    long_memory.delete(user_id, m["id"])
                
                consolidated_count += len(to_merge)
                logger.info(
                    f"合并记忆: user={user_id}, 合并 {len(group)} 条为 1 条"
                )
    
    logger.info(f"记忆整合完成，共合并 {consolidated_count} 条记忆")


async def _find_merge_groups(memories, long_memory):
    """找出需要合并的记忆组。"""
    groups = []
    used = set()
    
    for i, m1 in enumerate(memories):
        if m1["id"] in used:
            continue
        
        group = [m1]
        
        for j, m2 in enumerate(memories):
            if j <= i or m2["id"] in used:
                continue
            
            # 计算相似度
            similarity = await _calculate_similarity(m1, m2, long_memory)
            
            if similarity >= CONSOLIDATION_THRESHOLD:
                group.append(m2)
                used.add(m2["id"])
        
        if len(group) > 1:
            used.add(m1["id"])
            groups.append(group)
    
    return groups


async def _calculate_similarity(m1, m2, long_memory):
    """计算两条记忆的相似度。"""
    # 如果有 embedding，使用向量相似度
    if m1.get("embedding") and m2.get("embedding"):
        from app.memory.long_memory import _cosine
        return _cosine(m1["embedding"], m2["embedding"])
    
    # 否则使用 bigram 相似度
    from app.memory.long_memory import bigram_relevance
    return bigram_relevance(m1["content"], m2["content"])

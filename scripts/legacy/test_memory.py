"""测试记忆系统"""
import asyncio
from app.memory.memory_manager import MemoryManager

async def test():
    mm = MemoryManager()
    user_id = 'e_UfToQjT5ido'  # 王奶奶

    # 1. 检查短期记忆（最近6轮对话）
    print('=== 短期记忆（最近6轮） ===')
    history = mm.short.recent_messages(user_id)
    for role, content in history[-12:]:
        print(f'{role}: {content[:50]}...' if len(content) > 50 else f'{role}: {content}')

    # 2. 检查长期记忆
    print('\n=== 长期记忆 ===')
    memories = mm.long.list_all(user_id)
    for m in memories:
        print(f'[{m["memory_type"]}] {m["content"]} (重要性: {m["importance"]})')

    # 3. 测试记忆检索
    print('\n=== 记忆检索测试 ===')
    test_queries = ['孙子', '红烧排骨', '年龄', '今天']
    for query in test_queries:
        results = await mm.long.search_multi(user_id, [query])
        print(f'查询 "{query}": {len(results)} 条结果')
        for r in results[:2]:
            print(f'  - {r["content"]} (分数: {r["score"]})')

if __name__ == '__main__':
    asyncio.run(test())

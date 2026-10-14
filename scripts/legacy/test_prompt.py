"""测试画像注入到 prompt 的完整流程"""
import asyncio
from app.memory.memory_manager import MemoryManager
from app.companion.prompts import build_messages
from app.emotion.emotion_analyzer import AnalysisResult

async def test():
    mm = MemoryManager()
    user_id = 'e_UfToQjT5ido'  # 王奶奶

    # 模拟一个分析结果
    analysis = AnalysisResult(
        emotion='happy',
        emotion_intensity=0.8,
        intent='casual_chat',
        topic='孙子',
        scene='conversation',
        need='none',
        risk_level='low',
    )

    # 构建上下文
    ctx = await mm.build_context(user_id, '我孙子今天要来', analysis)

    # 构建 prompt
    messages = build_messages(ctx, '我孙子今天要来')

    print('=== System Prompt ===')
    print(messages[0]['content'])
    print('\n=== 历史消息 ===')
    for msg in messages[1:]:
        print(f'{msg["role"]}: {msg["content"][:50]}...' if len(msg["content"]) > 50 else f'{msg["role"]}: {msg["content"]}')

if __name__ == '__main__':
    asyncio.run(test())

"""导入内置 RAG 知识资料。

用法：
    python scripts/seed_knowledge.py
    python scripts/seed_knowledge.py --no-embed  # 离线导入，使用关键词检索兜底

脚本可重复执行：相同内容不会重复写入。默认资料是系统公共资料，
created_by 为空，因此所有老人都可以检索到。
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from app.db.base import dispose_engine, init_async_db  # noqa: E402
from app.rag.knowledge_base import KnowledgeBase  # noqa: E402


async def seed(no_embed: bool = False) -> None:
    await init_async_db()
    embed_fn = (lambda _texts: None) if no_embed else None
    knowledge = KnowledgeBase(embed_fn=embed_fn)
    source_path = ROOT / "data" / "knowledge_base.json"
    items = json.loads(source_path.read_text(encoding="utf-8"))
    for item in items:
        result = await knowledge.add_document(
            item["title"], item["content"], source=item.get("source", ""),
        )
        print(
            f"已处理：{result['title']}（{result['chunk_count']} 个分块，"
            f"向量={'是' if result.get('embedded') else '否'}）"
        )
    if not no_embed:
        updated = await knowledge.reindex_missing()
        print(f"已补建 {updated} 个分块的语义向量。")
    documents = await knowledge.list_documents()
    print(f"知识库当前共有 {len(documents)} 篇文档，{sum(d['chunk_count'] for d in documents)} 个分块。")
    await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="导入陪伴 AI 内置 RAG 知识资料")
    parser.add_argument("--no-embed", action="store_true", help="不调用远程 embedding，使用关键词检索兜底")
    args = parser.parse_args()
    asyncio.run(seed(no_embed=args.no_embed))

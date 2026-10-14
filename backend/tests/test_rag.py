"""RAG 知识库的离线单元测试，不调用 Qwen。"""
import asyncio
import os
import tempfile

_rag_db_dir = tempfile.mkdtemp(prefix="companion_rag_")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///" + os.path.join(_rag_db_dir, "rag.db").replace("\\", "/")
os.environ["JWT_SECRET_KEY"] = "test-secret"


def _fake_embed(texts):
    """确定性字符桶向量，验证存储与检索管线。"""
    vectors = []
    for text in texts:
        vector = [0.0] * 256
        for char in text:
            vector[ord(char) % 32] += 1.0
        norm = sum(value * value for value in vector) ** 0.5 or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


def test_split_text_keeps_content_and_overlap():
    from app.rag.knowledge_base import split_text

    text = "第一段。" * 120
    chunks = split_text(text, chunk_size=100, overlap=20)
    assert len(chunks) > 1
    assert "第一段" in "".join(chunks)
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_knowledge_add_search_and_scope():
    async def run():
        from app.db.base import dispose_engine, init_async_db
        from app.rag.knowledge_base import KnowledgeBase

        await dispose_engine()
        await init_async_db()
        kb = KnowledgeBase(embed_fn=_fake_embed)
        global_doc = await kb.add_document(
            "跌倒处理", "老人跌倒后先保持平静，不要急着扶起，应观察是否受伤并联系家人。",
            source="护理手册",
        )
        private_doc = await kb.add_document(
            "王阿姨偏好", "王阿姨喜欢在下午听邓丽君。", scope="elderly",
            elderly_user_id="elderly_1", created_by="family_1",
        )
        assert global_doc["chunk_count"] == 1
        assert private_doc["scope"] == "elderly"

        hits = await kb.search("跌倒之后应该怎么办", user_id="elderly_2")
        assert hits and hits[0]["title"] == "跌倒处理"
        private_hits = await kb.search("喜欢听什么歌", user_id="elderly_1")
        assert private_hits and private_hits[0]["title"] == "王阿姨偏好"
        assert not any(
            hit["title"] == "王阿姨偏好"
            for hit in await kb.search("喜欢听什么歌", user_id="elderly_2")
        )
        assert await kb.delete_document(global_doc["id"], created_by="other") is False
        assert await kb.delete_document(global_doc["id"], created_by="family_1") is False
        assert await kb.delete_document(global_doc["id"]) is True
        await dispose_engine()

    asyncio.run(run())

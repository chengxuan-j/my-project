"""探针脚本的共用件（不对外，仅供 scripts/ 下的探针 import）。

为什么要有它：M0 的提取要 `QWEN_API_KEY`，本地没配时拿不到真实 `era_tags` /
`narration` 素材，M3 时代轴与 M5 故事板的**真实语料验收**就没法做。两个探针
都用「语料里的人工真值标签」当**离线替身提取器**，把链路完整跑一遍。

三条硬约束，两个探针共用：
- **绝不碰真实库**：默认指到系统临时目录的一次性 SQLite，跑完即删；
- **不改语料**：只读 `data/demo_conversations_elderly_001.json`；
- **明示替身性质**：替身提取器只用于打通编排链路，不代表模型真实产出。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

CORPUS_PATH = ROOT / "data" / "demo_conversations_elderly_001.json"


def use_temp_db(name: str) -> Path:
    """把 DATABASE_URL 指到临时库。**必须在 import app.* 之前调用。**

    会先删掉同名旧文件：上一次探针若因异常提前退出（清理没跑到），
    残留库会让这一次灌语料时撞 `UNIQUE constraint failed: accounts.username`。
    一次性临时库本就该每次从零开始。
    """
    tmp = Path(tempfile.gettempdir()) / f"{name}.sqlite3"
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass  # 上次的进程还握着文件句柄时不阻塞启动，后续会自然失败并报出来
    os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{tmp.as_posix()}")
    os.environ.setdefault("JWT_SECRET_KEY", "probe-secret")
    return tmp


def load_corpus() -> dict:
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def label_to_extraction(turn: dict) -> dict:
    """把语料的人工标签翻译成 `story_extractor._normalize` 的输出形状。

    这是「离线替身提取器」——只用于打通 M3/M4/M5 编排链路，不参与生产路径。
    `missing` 必须带上：M4 的缺口队列就是从它推导的，漏了的话追问回放会空转。
    """
    label = turn.get("label") or {}
    return {
        "is_life_story": True,
        "title": turn.get("topic") or "",
        "summary": (turn.get("user") or "")[:60],
        "time": {"type": "relative", "value": "", "confidence": 0.0},
        "era_tags": list(label.get("era_tags") or []),
        "place": "",
        "people": [],
        "emotion_tone": label.get("emotion_tone") or "平淡",
        "missing": list(label.get("missing") or []),
        "follow_up_hint": label.get("follow_up_hint") or "",
        "confidence": 0.9,
    }


def check_label_drift(corpus: dict) -> tuple[list[str], list[str]]:
    """语料标签 → 规范名的归一检查。返回 (命中的规范名, 归一不上的原始标签)。"""
    from app.memoir import era_lexicon

    seen: list[str] = []
    unmapped: list[str] = []
    for turn in corpus.get("turns", []):
        for raw in (turn.get("label") or {}).get("era_tags") or []:
            canonical, missing = era_lexicon.normalize_tags([raw])
            for name in canonical:
                if name not in seen:
                    seen.append(name)
            for miss in missing:
                if miss not in unmapped:
                    unmapped.append(miss)
    seen.sort(key=lambda n: (era_lexicon.era_meta(n) or {}).get("start_year") or 9999)
    return seen, unmapped


async def seed_corpus_stories(corpus: dict, *, status: str = "archived") -> tuple[str, int]:
    """把语料正例灌成 life_stories，返回 **(真实账号 user_id, 条数)**。

    注意返回值是 `acc.user_id`（形如 `e_8XlY5v8E6Y4`），不是语料里的
    `corpus["user_id"]`（`elderly_001`）——后者只是语料里的业务标识，
    落库时账号 id 由 `AccountRepo` 生成。这两者混用会让后续查询一条都查不到。

    画像字段原样灌进去——M3 的 P4 保守推断与 M5 的故事板都依赖它。
    """
    from sqlalchemy import select

    from app.db.base import dispose_engine, get_session_factory, init_async_db
    from app.db.models import ElderlyProfile
    from app.repositories.account_repo import AccountRepo
    from app.repositories.story_repo import StoryRepo

    await dispose_engine()
    await init_async_db()

    prof = corpus.get("profile") or {}

    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_elderly(
            corpus.get("user_id", "elderly_001"), "probe-pwd",
            name=prof.get("name", "老人家"),
        )
        row = (await session.execute(
            select(ElderlyProfile).where(ElderlyProfile.user_id == acc.user_id)
        )).scalar_one()
        row.life_experience = list(prof.get("life_experience") or [])
        row.family = list(prof.get("family") or [])
        await session.commit()

        repo = StoryRepo(session)
        created = 0
        for turn in corpus.get("turns", []):
            if not (turn.get("label") or {}).get("is_life_story"):
                continue
            await repo.create(
                acc.user_id,
                title=turn.get("topic", ""),
                summary=(turn.get("user") or "")[:60],
                # 老人原话存进 raw_dialogue：M5 的旁白优先用它（契约4）
                raw_dialogue=[
                    {"role": "user", "content": turn.get("user") or ""},
                    {"role": "assistant", "content": turn.get("assistant") or ""},
                ],
                era_tags=list((turn.get("label") or {}).get("era_tags") or []),
                emotion_tone=(turn.get("label") or {}).get("emotion_tone") or "平淡",
                completeness=0.6,
                status=status,
                visibility="family",
            )
            created += 1
        await session.commit()

    return acc.user_id, created


def cleanup(path: Path) -> None:
    """删掉临时库（顺带清 SQLite 的 -wal/-shm/-journal 旁文件）。

    **必须先释放引擎句柄**：Windows 上文件被进程占着时 `unlink` 会抛
    `PermissionError`，而探针的 `finally` 跑在进程退出之前，句柄还没关——
    早期版本就是这么静默漏下四个几百 KB 的临时库的（异常被吞了，看不见）。
    """
    try:
        import asyncio

        from app.db.base import dispose_engine

        asyncio.run(dispose_engine())
    except Exception:
        # 事件循环已在跑 / 模块未导入：尽力而为，下面的 unlink 仍然会试
        pass

    for suffix in ("", "-journal", "-wal", "-shm"):
        target = path.with_name(path.name + suffix) if suffix else path
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass

"""M6 家属端回忆录验收探针：用**真实语料**跑一遍「家属看得到什么、改得动什么」。

为什么单独写一个探针：单测里只有两三条手搓故事，看不出**规模**下的行为——
比如"家属可见条数与老人留档条数是否对得上""收回可见性后时间轴少了几条"。
这里灌真语料（正例 40 条），走完整 HTTP 栈（ASGI）而不是直接调函数。

覆盖四件事：
1. 家属时间轴只含 `archived` + `family/public` 的故事；
2. 家属能给这些故事补照片，老人时间轴上立刻看得到同一张；
3. 老人把某段改成 `private` → 家属**立刻**读不到那张照片（404）、时间轴也少一条；
4. 家属没有任何编排写路径（确认留档 / 排短片 → 405）。

三条硬约束（沿用 `_probe_common`）：绝不碰真实库、不改语料、照片落在临时目录。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

from _probe_common import (  # noqa: E402  （必须先 use_temp_db 再 import app.*）
    CORPUS_PATH,
    cleanup,
    load_corpus,
    seed_corpus_stories,
    use_temp_db,
)

_TMP_DB = use_temp_db("memoir_family_probe")

import os  # noqa: E402
import tempfile  # noqa: E402

# 照片落在临时目录：探针不该在 storage/ 旁边留下任何东西
_MEDIA_DIR = Path(tempfile.gettempdir()) / "memoir_family_probe_media"
os.environ.setdefault("MEMOIR_MEDIA_DIR", _MEDIA_DIR.as_posix())

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.db.base import get_session_factory  # noqa: E402
from app.main import app  # noqa: E402
from app.repositories.account_repo import AccountRepo  # noqa: E402
from app.repositories.profile_repo import FamilyRepo  # noqa: E402
from app.repositories.story_repo import StoryMediaRepo, StoryRepo  # noqa: E402

# 一张最小的合法 PNG（只要文件头能被认出即可，不参与解码）
PNG = b"\x89PNG\r\n\x1a\n" + b"probe-photo-payload" * 4


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_family(bind_to: str) -> tuple[str, str]:
    async with get_session_factory()() as session:
        acc = await AccountRepo(session).create_family(
            "probe_family", "probe-pwd", email="probe_family@example.com"
        )
        await FamilyRepo(session).bind(acc.user_id, bind_to, "女儿")
        await session.commit()
    return acc.user_id, create_access_token(acc.user_id, role="family")


def _stories(tl: dict) -> list[dict]:
    return (
        [s for g in tl["era_axis"] for s in g["stories"]]
        + list(tl["absolute_axis"])
        + list(tl["unlocated"])
    )


async def run(corpus: dict, upload_count: int) -> dict:
    elderly_id, created = await seed_corpus_stories(corpus, status="archived")
    family_id, ftoken = await _seed_family(elderly_id)
    etoken = create_access_token(elderly_id, role="elderly")

    out: dict = {"elderly_id": elderly_id, "created": created, "checks": []}

    def check(name: str, ok: bool, detail: str = "") -> None:
        out["checks"].append((name, ok, detail))

    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://probe") as ac:
        fam_tl = (await ac.get(f"/api/v1/family/elderly/{elderly_id}/memoir",
                               headers=_auth(ftoken))).json()
        fam_stories = _stories(fam_tl)
        out["family_seen"] = len(fam_stories)
        check(
            "家属时间轴条数 == 老人留档条数（全部 family 可见）",
            len(fam_stories) == created,
            f"{len(fam_stories)} / {created}",
        )

        # ---- 家属给前 upload_count 段补照片 ----
        targets = fam_stories[:upload_count]
        uploaded: list[tuple[int, int]] = []   # (story_id, media_id)
        for i, s in enumerate(targets):
            payload = PNG + f"-{i}".encode()
            r = await ac.post(
                f"/api/v1/family/elderly/{elderly_id}/memoir/stories/{s['id']}/media",
                headers=_auth(ftoken),
                files={"file": (f"p{i}.png", payload, "image/png")},
                data={"caption": f"第 {i + 1} 张老照片"},
            )
            if r.status_code == 200:
                uploaded.append((s["id"], r.json()["id"]))
        out["uploaded"] = len(uploaded)
        check("家属能给可见的往事补照片", len(uploaded) == len(targets),
              f"{len(uploaded)} / {len(targets)}")

        # ---- 老人时间轴应看到同样的照片 ----
        owner_tl = (await ac.get("/api/v1/memoir/timeline", headers=_auth(etoken))).json()
        owner_media = {
            m["id"]: m for s in _stories(owner_tl) for m in (s["media"] or [])
        }
        same_ids = {mid for _sid, mid in uploaded} & set(owner_media)
        check("老人时间轴能看到家属补的照片", len(same_ids) == len(uploaded),
              f"{len(same_ids)} / {len(uploaded)}")
        check(
            "照片在响应里只暴露角色、不暴露上传者 user_id",
            all(m["uploaded_by_role"] in ("owner", "family") for m in owner_media.values())
            and family_id not in str(owner_media),
        )

        # ---- 家属读得到照片字节 ----
        read_ok = 0
        for _sid, mid in uploaded:
            r = await ac.get(f"/api/v1/memoir/media/{mid}", headers=_auth(ftoken))
            if r.status_code == 200 and r.content.startswith(b"\x89PNG"):
                read_ok += 1
        check("家属能读到照片字节（鉴权接口，不是静态目录）",
              read_ok == len(uploaded), f"{read_ok} / {len(uploaded)}")

        # ---- 老人收回第一段的可见性 → 家属立刻看不到 ----
        victim_story, victim_media = uploaded[0]
        async with get_session_factory()() as session:
            await StoryRepo(session).set_visibility(victim_story, "private")
            await session.commit()

        after = (await ac.get(f"/api/v1/family/elderly/{elderly_id}/memoir",
                              headers=_auth(ftoken))).json()
        after_ids = {s["id"] for s in _stories(after)}
        out["family_seen_after"] = len(after_ids)
        check("老人改成 private 后，家属时间轴少一条",
              len(after_ids) == len(fam_stories) - 1,
              f"{len(after_ids)} ← {len(fam_stories)}")
        check("该条不再出现在家属时间轴里", victim_story not in after_ids)
        check(
            "该条的照片对家属立刻 404",
            (await ac.get(f"/api/v1/memoir/media/{victim_media}",
                          headers=_auth(ftoken))).status_code == 404,
        )
        check(
            "但老人本人照样能看",
            (await ac.get(f"/api/v1/memoir/media/{victim_media}",
                          headers=_auth(etoken))).status_code == 200,
        )

        # ---- 家属没有任何编排/确认的写路径 ----
        base = f"/api/v1/family/elderly/{elderly_id}/memoir/compilations"
        check("家属不能排短片（POST 集合路径 405）",
              (await ac.post(base, headers=_auth(ftoken),
                             json={"title": "x"})).status_code == 405)
        check("家属不能删短片（DELETE 项路径 405）",
              (await ac.delete(f"{base}/1", headers=_auth(ftoken))).status_code == 405)
        check("家属不能替老人确认留档（老人端接口 403）",
              (await ac.post("/api/v1/stories/1/confirm",
                             headers=_auth(ftoken), json={"via": "button"})
               ).status_code == 403)

        # ---- 家属撤回自己补的照片 ----
        remaining = [(sid, mid) for sid, mid in uploaded[1:]]
        if remaining:
            _sid, mid = remaining[0]
            deleted = (await ac.delete(
                f"/api/v1/family/elderly/{elderly_id}/memoir/media/{mid}",
                headers=_auth(ftoken),
            )).status_code == 200
            async with get_session_factory()() as session:
                gone = await StoryMediaRepo(session).get(mid) is None
            check("家属能撤回自己补的照片", deleted and gone)
        check(
            "家属删不掉老人自己传的照片",
            await _family_cannot_delete_owner_photo(ac, elderly_id, etoken, ftoken),
        )

    return out


async def _family_cannot_delete_owner_photo(ac, elderly_id, etoken, ftoken) -> bool:
    """老人自己传一张，家属尝试删 → 应当 404（只能撤自己的）。"""
    tl = (await ac.get("/api/v1/memoir/timeline", headers=_auth(etoken))).json()
    stories = _stories(tl)
    alive = [s for s in stories if s["id"] != 0]
    if not alive:
        return False
    sid = alive[-1]["id"]
    r = await ac.post(
        f"/api/v1/memoir/stories/{sid}/media",
        headers=_auth(etoken),
        files={"file": ("own.png", PNG + b"-owner", "image/png")},
        data={"caption": "老人自己传的"},
    )
    if r.status_code != 200:
        return False
    mid = r.json()["id"]
    return (await ac.delete(
        f"/api/v1/family/elderly/{elderly_id}/memoir/media/{mid}",
        headers=_auth(ftoken),
    )).status_code == 404


def render(out: dict) -> str:
    lines = [
        f"语料：{CORPUS_PATH.name}｜老人：{out['elderly_id']}｜留档故事 {out['created']} 条",
        f"家属可见 {out['family_seen']} 条 → 补了 {out['uploaded']} 张照片"
        f" → 收回 1 条后剩 {out['family_seen_after']} 条",
        "-" * 66,
    ]
    for name, ok, detail in out["checks"]:
        mark = "✅" if ok else "❌"
        lines.append(f"  {mark} {name}" + (f"（{detail}）" if detail else ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uploads", type=int, default=5, help="给前几段补照片")
    args = parser.parse_args()

    corpus = load_corpus()
    md5 = hashlib.md5(CORPUS_PATH.read_bytes()).hexdigest()[:8]
    verdict = False
    try:
        out = asyncio.run(run(corpus, args.uploads))
        print(render(out))
        print(f"语料指纹 md5[:8]={md5}（确认本次跑的是哪份语料）")
        bad = [c for c in out["checks"] if not c[1]]
        verdict = not bad
        print("-" * 66)
        print(f"验收（M6 家属端可见性与写权限）：{'通过' if verdict else '不通过'}")
    finally:
        cleanup(_TMP_DB)
        # 清掉探针落盘的照片
        import shutil

        shutil.rmtree(_MEDIA_DIR, ignore_errors=True)
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""短片草稿箱的对话式引导：顺着老人说的话，接一句、推一句。

定位很窄：**只负责"小忆下一句说什么"**，不存故事、不改原文、不做总结。
故事存不存、存成什么样，仍然走 `create_manual_story` 那条确定的路。

对话的两条底线（这条链路的"好不好用"几乎全在这里）：

1. **要有往前的推力**。不能一直围着刚才那个细节打转——老人说完一段，
   最自然的是"后来呢？"，让他接着往下讲，故事才会长出来。
2. **要先接住情绪再问**。老人说到冷、饿、难、高兴、害怕，先应一句
   （"听着就够呛。"）再往下问，否则就像审讯，不是陪聊。

不设轮次上限、也不做"收尾"：老人愿意讲就一直陪着讲，讲完自己点保存。
任何时候点保存，都按当前全部原话存下来。

实现仍是「LLM 出话 + 硬校验 + 规则兜底」三段式：
LLM 给的句子必须过长度/问号/重复校验，任何一项不过就退规则句；
LLM 超时或报错同样退规则句。规则句按「先共情、再推进」的顺序拼，
保证任何情况下都能接上下一句。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional, Sequence

from app.core.json_utils import parse_json_loose
from app.llm.qwen_client import LLMError, QwenClient

logger = logging.getLogger(__name__)

# 单句长度上限（模型偶尔会写成一段话）
MAX_REPLY_LEN = 40

# 追问维度：progress = 把故事往前推，其余是补细节
FOCUS_ORDER = ("time", "place", "people", "detail", "feeling", "progress")

FOCUS_LABEL = {
    "time": "时间",
    "place": "地点",
    "people": "人物",
    "detail": "情形",
    "feeling": "感受",
    "progress": "往后发展",
}

# 往前推的问句：轮流用，避免连着几轮都是"后来呢"
PROGRESS_QUESTIONS = (
    "后来呢？",
    "再往后呢？",
    "那之后呢？",
    "接着又出了什么事？",
    "再往后就怎么样了？",
)

# 补细节的问句（只在故事停下来、或者老人主动回忆时用）
RULE_QUESTIONS = {
    "time": "这事是哪一年的事？",
    "place": "那地方在哪儿？",
    "people": "当时还有谁在？",
    "detail": "那会儿是怎么个情形？",
    "feeling": "那时候心里什么滋味？",
}

# 「听着就……」这类套话一律不要：老人听着像机器人在背模板。
# 命中即判不合格，退规则句（规则句只推进、不套话）。
BANNED_CLICHES = ("听着就", "听起来", "真不容易", "真够呛", "太不容易", "真辛苦")

# 老人明显不想说这段时的转向句（不追问，不勉强）
AVOID_MARKERS = ("不记得", "记不清", "忘了", "不想说", "别问了", "没啥好说")
AVOID_REPLY = "那咱不聊这个。您年轻时最常去的是哪儿？"

# 沉重话题（有人离世、离别、病痛）：这时候催"后来又出了什么事"太伤人，
# 换成一句贴人的问法——不是套话，是真的在问他当时怎么过的。
HEAVY_MARKERS = ("去世", "过世", "走了", "没了", "不在了", "病重", "住院", "葬礼", "临走")
HEAVY_REPLIES = (
    "您后来去送他了吗？",
    "那段日子您是怎么过来的？",
    "后来您还常想起他吗？",
)

# 说明：这几个维度只用于给模型提示"还缺什么"，不再作为硬性轮次节奏
DETAIL_MIN_CHARS = 80

SYSTEM_PROMPT = f"""你是「小忆」，陪老人聊往事的晚辈。老人正在讲自己的一段经历，你要像听故事一样接话，让他愿意一直往下讲。

【怎么接话】
- 主要是**往前推**：「后来呢？」「再往后呢？」「那之后呢？」——老人讲完一段，最自然的就是这一句。
- 想表示理解，就**提一件他说过的事**，比如「席棚里那个冬天可不好过」；或者干脆不接，直接往下问。
- **禁止套话**：不要用「听着就……」「听起来……」「真不容易」「真够呛」这类口气。
  这些话说出来像模板，老人听着别扭。

【规则】
- 一句话，不超过 24 个字，口语，像坐在旁边听；整句必须以问句结尾。
- 不要连着两轮都围着同一个细节问。
- 不评价他做得对不对，不总结，不讲道理，不一次问两件事，不重复已经问过的句子。
- 共情只能依据他说过的话，不要自己猜季节、天气、身体感受；
  也别替他补出没说过的场景（他没提"一个人在家"，就别这么问）。
- 他如果回避（"不记得了""不想说"），就轻轻转个方向，别硬问。
- **碰到有人去世、生重病、离别这种话，别催着问"后来又出了什么事"**。
  换一句贴人的问法：跟这个人有关的、他当时怎么过的，比如「您后来去送他了吗？」
  「那段日子您是怎么过来的？」。也不要讲道理、不要劝他"想开点"。
- 没有轮次限制：他愿意讲，你就一直陪着往下聊，不要说"差不多了""要不要保存"。

【输出】只输出一个 JSON 对象，不要输出其他任何文字
{{"reply": "后来呢？", "move": "progress|detail|feeling", "focus": "time|place|people|detail|feeling|progress"}}"""


def _norm(text: str) -> str:
    """比对重复用：去掉标点空白。"""
    return re.sub(r"[\s，。、！？,.!?…~～\"'“”‘’]", "", text or "")


def _user_text(turns: Sequence[dict]) -> str:
    return "\n".join(
        str(t.get("content") or "") for t in turns if t.get("role") == "user"
    )


def _last_user_text(turns: Sequence[dict]) -> str:
    for t in reversed(list(turns)):
        if t.get("role") == "user":
            return str(t.get("content") or "")
    return ""


def _asked(turns: Sequence[dict]) -> list[str]:
    return [str(t.get("content") or "") for t in turns if t.get("role") == "assistant"]


def _covered(text: str, focus: str) -> bool:
    """老人自己的话里是否已经覆盖这个维度（只用于给模型提示还缺什么）。"""
    hints = {
        "time": ("年", "岁", "春", "夏", "秋", "冬", "月", "日", "时候", "解放前", "小时候"),
        "place": ("村", "城", "县", "镇", "厂", "学校", "家里", "院子", "工地"),
        "people": ("妈", "爸", "娘", "爹", "哥", "姐", "弟", "妹", "孩子", "老伴",
                   "工友", "老师", "同学", "邻居", "老王", "他们"),
        "feeling": ("高兴", "开心", "难过", "舍不得", "怕", "苦", "累", "甜", "心酸", "委屈"),
    }
    if focus == "detail":
        return len(text) >= DETAIL_MIN_CHARS
    return any(h in text for h in hints.get(focus, ()))


def rule_reply(turns: Sequence[dict]) -> dict[str, Any]:
    """规则兜底：只把话往下推，不套模板。永远能给出输出。"""
    asked = _asked(turns)
    asked_norm = {_norm(a) for a in asked}
    last_user = _last_user_text(turns)

    if any(m in last_user for m in AVOID_MARKERS):
        return {"question": AVOID_REPLY, "focus": "progress",
                "done": False, "source": "rule"}

    # 沉重话题优先：这时候"后来又出了什么事"会显得冷漠
    if any(m in last_user for m in HEAVY_MARKERS):
        for q in HEAVY_REPLIES:
            if _norm(q) not in asked_norm:
                return {"question": q, "focus": "feeling",
                        "done": False, "source": "rule"}

    # 推进优先：前两轮直接往前推，之后按"推进 / 补细节"交替
    round_no = len(asked)
    question = ""
    if round_no < 2:
        for q in PROGRESS_QUESTIONS:
            if _norm(q) not in asked_norm:
                question = q
                break
    if not question:
        candidates = (
            list(PROGRESS_QUESTIONS[round_no % len(PROGRESS_QUESTIONS):])
            + list(PROGRESS_QUESTIONS[: round_no % len(PROGRESS_QUESTIONS)])
            + [RULE_QUESTIONS[k] for k in ("people", "place", "detail", "feeling", "time")]
        )
        for q in candidates:
            if _norm(q) not in asked_norm:
                question = q
                break
    if not question:
        question = "后来又想到什么了？"

    return {"question": question, "focus": "progress", "done": False, "source": "rule"}


def _transcript(turns: Sequence[dict]) -> str:
    lines = []
    for t in turns:
        who = "老人" if t.get("role") == "user" else "小忆"
        lines.append(f"{who}：{str(t.get('content') or '').strip()}")
    return "\n".join(lines)


# 问句特征词：模型常把一句感叹硬加问号（"那真够早的？"），那种句子接不住话。
_QUESTION_MARKERS = (
    "呢", "吗", "什么", "怎么", "咋", "哪", "谁", "几", "多少", "为什么", "如何", "是不是", "有没有",
)


def _looks_like_question(q: str) -> bool:
    """结尾是问号，且带疑问词——否则就是陈述句硬加问号，退规则句。"""
    if not q.endswith(("？", "?")):
        return False
    return any(m in q for m in _QUESTION_MARKERS)


def _tail(q: str) -> str:
    """取一句话里的问句部分（"听着就冷。后来呢？" → "后来呢？"）。"""
    return q.split("。")[-1]


def _vary_progress(q: str, asked: Sequence[str]) -> str:
    """上一句已经问过"后来呢？"时换一种说法，别让老人听着像复读机。"""
    prev_tails = {_norm(_tail(a)) for a in asked}
    if _norm(_tail(q)) not in prev_tails:
        return q
    for cand in PROGRESS_QUESTIONS:
        if _norm(cand) not in prev_tails:
            head = q[: q.rfind("。") + 1] if "。" in q else ""
            varied = f"{head}{cand}"
            return varied if len(varied) <= MAX_REPLY_LEN else cand
    return q


def _clean_reply(raw: Any, asked: Sequence[str] = ()) -> Optional[str]:
    """校验模型给的一句话：短、口语、是个真问句，且不是复述。

    命中「听着就……」这类套话时：能截掉前半句就截（保留真正的问句），
    截不出来就判不合格、退规则句——这类话在演示里最出戏。
    """
    if not isinstance(raw, str):
        return None
    q = raw.strip().strip("「」\"'“”")
    q = re.sub(r"\s+", "", q)
    if not q or "\n" in q:
        return None
    if len(q) > MAX_REPLY_LEN:
        return None
    if not _looks_like_question(q):
        return None
    for w in BANNED_CLICHES:
        if w in q:
            tail = q.split("。", 1)[1] if "。" in q else ""
            if tail and _looks_like_question(tail):
                q = tail
            else:
                return None
            break
    return _vary_progress(q, asked)


async def next_reply(
    turns: Sequence[dict], *, client: Optional[Any] = None
) -> dict[str, Any]:
    """给出小忆的下一句话。

    返回 `{question, focus, done, source}`；`question` 字段名保持不变，
    前端当"小忆说的话"用。`done` 恒为 False——这条链路不再自动收尾。
    """
    turns = list(turns)
    asked_norm = {_norm(a) for a in _asked(turns)}

    llm = client or QwenClient()
    text = _user_text(turns)
    covered = [FOCUS_LABEL[f] for f in FOCUS_ORDER if _covered(text, f)]
    missing = [FOCUS_LABEL[f] for f in FOCUS_ORDER if not _covered(text, f)]
    asked = _asked(turns)
    last_user = _last_user_text(turns)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "这是到目前为止的对话：\n"
                f"{_transcript(turns)}\n\n"
                f"老人刚说的是：{last_user}\n"
                f"他已经提到的：{'、'.join(covered) or '还不清楚'}\n"
                f"还缺的：{'、'.join(missing) or '基本都有了'}\n"
                + (f"已经问过的：{' / '.join(asked)}\n" if asked else "")
                + "请先接住他的情绪，再把故事往前推一句（比如「后来呢？」），不要重复刚才问过的。"
            ),
        },
    ]
    try:
        raw = await llm.chat(
            messages,
            model=getattr(llm, "analysis_model", None) or None,
            temperature=0.6,
            max_tokens=120,
        )
        data = parse_json_loose(raw)
        if isinstance(data, dict):
            q = _clean_reply(data.get("reply") or data.get("question"), asked)
            focus = str(data.get("focus") or "").strip()
            if focus not in FOCUS_ORDER:
                focus = "progress"
            if q and _norm(q) not in asked_norm:
                return {"question": q, "focus": focus, "done": False, "source": "llm"}
        q = _clean_reply(raw, asked)
        if q and _norm(q) not in asked_norm:
            return {"question": q, "focus": "progress", "done": False, "source": "llm"}

        logger.info("追问输出不合格，退规则句 raw=%s", str(raw)[:80])
    except LLMError as e:
        logger.warning("追问调用失败，退规则句：%s", e)
    except Exception as e:  # noqa: BLE001 - 兜底不能把接口打挂
        logger.warning("追问异常，退规则句：%s", e)

    return rule_reply(turns)


# 兼容旧调用名（接口层已改为 next_reply）
next_question = next_reply

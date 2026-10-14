"""益智游戏：数字记忆 / 成语接龙 / 简单算术。

设计文档第二十一节：由 Qwen 生成互动内容，不做复杂游戏引擎。
实现策略：出题/判题逻辑本地规则化（无状态、确定性、可测试），
成语接龙等开放内容在 Qwen 可用时用其生成，不可用（欠费/断网）时用内置词表兜底。
"""
import logging
import random
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 成语接龙内置小词表（Qwen 不可用时的兜底）
_IDIOM_STARTS = ["一心一意", "龙马精神", "心想事成", "万事如意", "花好月圆"]
_IDIOM_TAILS = {
    "一": ["一马当先", "一心一意", "一帆风顺"],
    "意": ["意气风发", "意想不到"],
    "神": ["神通广大"],
    "成": ["成千上万"],
    "圆": ["圆满成功"],
    "先": ["先人后己"],
    "发": ["发扬光大"],
    "大": ["大展宏图"],
    "万": ["万水千山"],
    "功": ["功德圆满"],
    "己": ["己所不欲"],
    "光": ["光明磊落"],
    "图": ["图穷匕见"],
    "山": ["山高水长"],
    "长": ["长命百岁"],
    "岁": ["岁月如歌"],
}


# ---------- 数字记忆 ----------

def number_memory_new(digits: int = 5) -> Dict[str, Any]:
    """出题：随机数字串（默认 5 位）。返回 {"kind": "number_memory", "sequence": ...}"""
    digits = max(3, min(digits, 9))
    seq = "".join(str(random.randint(0, 9)) for _ in range(digits))
    return {"kind": "number_memory", "sequence": seq,
            "prompt": f"请您记住这串数字：{seq}，然后按顺序说出来。"}


def number_memory_check(sequence: str, answer: str) -> Dict[str, Any]:
    """判题：对错 + 鼓励语。"""
    ok = answer.strip() == sequence.strip()
    return {
        "kind": "number_memory",
        "correct": ok,
        "feedback": "答对了，记性真好！" if ok
                    else f"没关系，正确答案是 {sequence}，再试一次新数字吧。",
    }


# ---------- 简单算术 ----------

def arithmetic_new(difficulty: str = "easy") -> Dict[str, Any]:
    """出题：两位数以内加减法。difficulty: easy / medium。"""
    if difficulty == "medium":
        a, b = random.randint(11, 99), random.randint(11, 99)
    else:
        a, b = random.randint(1, 50), random.randint(1, 50)
    op = random.choice(["+", "-"])
    if op == "-" and b > a:
        a, b = b, a
    answer = a + b if op == "+" else a - b
    return {"kind": "arithmetic", "question": f"{a} {op} {b} = ?",
            "answer": answer, "prompt": f"咱们来算一道题：{a} {op} {b} 等于多少？"}


def arithmetic_check(expected: int, answer: Any) -> Dict[str, Any]:
    try:
        ok = int(answer) == int(expected)
    except (TypeError, ValueError):
        return {"kind": "arithmetic", "correct": False,
                "feedback": "您说的是个数字吗？咱们再来一道。"}
    return {"kind": "arithmetic", "correct": ok,
            "feedback": "算得对，真厉害！" if ok
                        else f"差一点，答案是 {expected}。"}


# ---------- 成语接龙 ----------

async def idiom_chain_start(qwen_client=None) -> Dict[str, Any]:
    """开局：给一个起始成语。Qwen 可用时用其生成，否则用内置词表。"""
    idiom = (await _idiom_from_qwen(qwen_client)
             if qwen_client else random.choice(_IDIOM_STARTS))
    return {
        "kind": "idiom_chain",
        "start": idiom,
        "prompt": f"我们来玩成语接龙。我说：{idiom}。请您接一个，用最后一个字「{idiom[-1]}」开头。",
        "last_char": idiom[-1],
    }


def idiom_chain_check(start: str, user_idiom: str, qwen_client=None) -> Dict[str, Any]:
    """判题：是否正确以「start 的末字」开头。语义校验优先走 Qwen，否则仅做字头校验。"""
    user_idiom = (user_idiom or "").strip()
    if not user_idiom:
        return {"kind": "idiom_chain", "correct": False,
                "feedback": "您还没说呢，随便接一个试试。"}
    expected = start[-1]
    if not user_idiom.startswith(expected):
        return {"kind": "idiom_chain", "correct": False,
                "feedback": f"得用「{expected}」字开头哦，您再想想。"}
    return {
        "kind": "idiom_chain",
        "correct": True,
        "feedback": f"接得好！那我接着来：{_next_idiom(user_idiom)}",
        "last_char": user_idiom[-1],
    }


def _next_idiom(user_idiom: str) -> str:
    """内置词表续接（Qwen 不可用时）。"""
    tail = user_idiom[-1]
    candidates = _IDIOM_TAILS.get(tail)
    if candidates:
        return random.choice(candidates)
    # 兜底：直接重复提示
    return "……这个字有点难接，您先接一个试试？"


async def _idiom_from_qwen(client) -> Optional[str]:
    """用 Qwen 生成一个温和的起始成语。失败返回 None。"""
    try:
        reply = await client.chat(
            [{"role": "system",
              "content": "你帮老人玩成语接龙，只输出一个四字成语，不要解释。"},
             {"role": "user", "content": "随便说一个成语开头"}],
            temperature=0.7, max_tokens=16,
        )
        idiom = reply.strip().strip("。")
        return idiom if 2 <= len(idiom) <= 6 else None
    except Exception as e:  # noqa: BLE001
        logger.info("成语接龙 Qwen 生成失败，用内置词表: %s", e)
        return None

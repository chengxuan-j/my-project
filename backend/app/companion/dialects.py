"""方言模式：可选方言与提示词片段。

设计：
- 开关状态存在 `elderly_profiles.conversation_preferences["dialect_mode"]`，
  方言名存在 `elderly_profiles.dialect`。前者是"开不开"，后者是"哪一种"，
  分开存的好处是关掉方言后，老人选过的方言不会丢，下次打开还在。
- 提示词只约束**用词与语气**，不动长度与安全策略：方言也不能啰嗦，
  危机干预仍然走短句、标准表达（老人听得懂比"地道"重要）。
"""

from typing import Dict, List

# 老人端下拉框顺序：普通话 = 关闭方言
DIALECT_OPTIONS: List[str] = ["普通话", "四川话", "东北话", "粤语", "上海话", "河南话", "陕西话"]

# 每种方言的口语特征。写给模型看，不是给老人念的。
DIALECT_STYLE: Dict[str, str] = {
    "四川话": "用四川话的口语表达，可以用「啥子、要得、巴适、啷个、莫得、晓得」这类词，"
              "句尾自然带「嘛、噻、哦」",
    "东北话": "用东北话的口语表达，可以用「咋整、唠嗑、得劲儿、嗯哪、贼好、整明白」这类词，"
              "语气爽利热乎",
    "粤语": "用粤语口语表达（书面粤语，不要写成普通话直译），可以用「唔使、係、咁、食饭、"
            "多谢、早唞」这类词",
    "上海话": "用上海话的口语表达，可以用「侬、阿拉、勿、伊、老好、谢谢侬」这类词，语气温和",
    "河南话": "用河南话的口语表达，可以用「中、恁、咋、哩、得劲、管」这类词，朴实直爽",
    "陕西话": "用陕西话的口语表达，可以用「嫑、咋、嘹咋咧、额、谝闲传」这类词，语气憨厚",
}


def normalize_dialect(name: str) -> str:
    """把前端传来的方言名收敛到白名单；不认识的一律当普通话（=关闭）。"""
    name = (name or "").strip()
    if name in DIALECT_STYLE:
        return name
    return ""


def dialect_instruction(name: str) -> str:
    """生成注入 system prompt 的方言段；返回空串表示不启用。"""
    name = normalize_dialect(name)
    if not name:
        return ""
    style = DIALECT_STYLE[name]
    return "\n".join([
        f"【方言模式 · {name}】",
        "（以下要求优先于前面「使用中文」的通用要求，按这里说的方式说话。）",
        f"- {style}。",
        "- 整段回复都用这种口语，不要一半方言一半普通话，也不要解释你在说方言。",
        "- 老人用了方言词、同音字或者语序颠倒时，按方言里的意思去理解，不要纠正他的说法，"
        "也不要要求他说普通话；没听明白就顺着问一句。",
        "- 仍然保持简短口语、能被语音朗读；不要用生僻字、不要用拼音注音。",
        "- 如果遇到吃药、安全提醒、身体不舒服这类要紧事，先用老人习惯的说法讲清楚，"
        "必要时补一句普通话，确保他听得明白。",
    ])


def dialect_options() -> List[dict]:
    """给前端的状态接口用：列出可选项及是否支持。"""
    return [
        {"name": name, "enabled": name != "普通话", "style": DIALECT_STYLE.get(name, "")}
        for name in DIALECT_OPTIONS
    ]

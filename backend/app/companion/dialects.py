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
    "粤语": "用粤语口语表达（写成书面粤语），必须用「唔、咗、係、嘅、咁、喺、睇、食、瞓、佢」"
            "这类粤语字，不要写成普通话直译，也不要用普通话的语气词",
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


# TTS 的方言靠**专用音色**，不靠自然语言指令。
# 2026-10-27 实测：给老的 qwen-audio-3.0-tts-flash 传
# 「请用英文说这句话。」，出来的仍然是中文音频 —— instruction 根本没生效，
# 所以之前"方言播报"其实一直是普通话音色。真正能用的是 qwen3-tts 系列
# 的原生方言音色（四川 Sunny/Eric、粤语 Kiki/Rocky、上海 Jada、陕西 Marcus…）。
_TTS_VOICE_BY_DIALECT: Dict[str, str] = {
    "四川话": "Sunny",   # 四川-晴儿（女，甜）
    "粤语": "Kiki",      # 粤语-阿清（女，港妹）
    "上海话": "Jada",    # 上海-阿珍（女，沪上阿姐）
    "陕西话": "Marcus",  # 陕西-秦川（男，老陕）
}

# 没有原生音色的方言：文字可以用方言词，但播报只能是普通话音色
_NO_VOICE_DIALECTS = ("东北话", "河南话")


def tts_dialect_voice(name: str) -> str:
    """该方言对应的 TTS 音色名；没有原生音色返回空串。"""
    return _TTS_VOICE_BY_DIALECT.get(normalize_dialect(name), "")


def has_native_voice(name: str) -> bool:
    return bool(tts_dialect_voice(name))


def tts_dialect_instruction(name: str) -> str:
    """保留给"没有原生音色"的方言做语气提示（对模型基本无效，仅兼容旧调用）。"""
    name = normalize_dialect(name)
    if not name:
        return ""
    return f"请用{name}说这句话。"


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
        "- 不要只在普通话句子里塞一两个方言词充数：句式、语气词、称呼都要按方言来；"
        "「确实、因此、建议、需要注意、此外」这类书面词一个都不要用。",
        "- 老人用了方言词、同音字或者语序颠倒时，按方言里的意思去理解，不要纠正他的说法，"
        "也不要要求他说普通话；没听明白就顺着问一句。",
        "- 仍然保持简短口语、能被语音朗读；不要用生僻字、不要用拼音注音。",
        "- 如果遇到吃药、安全提醒、身体不舒服这类要紧事，先用老人习惯的说法讲清楚，"
        "必要时补一句普通话，确保他听得明白。",
    ])


def dialect_options() -> List[dict]:
    """给前端的状态接口用：列出可选项、语气说明，以及有没有原生方言音色。"""
    return [
        {
            "name": name,
            "enabled": name != "普通话",
            "style": DIALECT_STYLE.get(name, ""),
            # 没有原生音色 = 文字是方言，播报仍是普通话，前端要如实提示
            "has_voice": has_native_voice(name),
        }
        for name in DIALECT_OPTIONS
    ]

"""老人陪伴 System Prompt。

第 2 轮：在角色设定基础上注入【老人画像】与【当前话题/情绪】。
第 3/4 轮将继续注入长期记忆与情绪/场景分析结果。
"""

from typing import Optional

COMPANION_SYSTEM_PROMPT = """你是一名面向老年人的情感陪伴助手。

你的主要任务不是机械回答问题，而是理解老年人的表达、情绪、生活背景和当前场景，并提供自然、温和、有耐心的陪伴。

【输出长度要求 · 必须遵守】
{length_rule}
禁止排比、铺陈、散文式描写、括号旁白和 emoji。
输出会被语音朗读，只写简洁口语。

交流原则：

1. 使用自然、温和、容易理解的中文。
2. 不使用大量网络流行语。
3. 不要过度热情。
4. 不要连续提出多个问题。
5. 一次最多提出一个自然的问题。
6. 当老人倾诉时，优先倾听和共情。
7. 不要刚听到问题就马上给出大量建议。
8. 回复尽量像自然聊天，而不是客服话术。
9. 适当结合老人已经告诉你的个人信息。
10. 不得虚构老人没有说过的事情。
11. 不要假装自己是真人。
12. 不进行医疗诊断。
13. 不进行心理疾病诊断。
14. 遇到高风险内容时按照安全策略处理。
15. 回复只写 2~3 句、60 字以内，不要排比和铺陈。
16. 回复内容会被语音朗读，避免括号、书名号、emoji 等不便朗读的符号。"""


EMOTION_CN = {
    "neutral": "平静", "lonely": "孤独", "sad": "难过", "bored": "无聊",
    "happy": "开心", "anxious": "焦虑", "angry": "生气", "tired": "疲惫",
    "nostalgic": "怀旧", "grateful": "欣慰", "worried": "担忧",
}
SCENE_CN = {
    "conversation": "正在聊天", "alone": "独自在家", "family_visit": "家人陪伴",
    "mealtime": "吃饭时间", "morning": "清晨", "evening": "傍晚",
    "outdoor": "在户外", "rest": "休息时",
}
NEED_CN = {
    "companionship": "想要有人陪", "listening": "想被倾听",
    "distraction": "想找点事打发时间", "information": "想得到信息",
    "reminder": "想要提醒", "praise": "想要被肯定", "comfort": "想被安慰",
    "none": "",
}


def _state_block(ctx) -> str:
    """注入本轮情境分析结果（第 4 轮起为 Qwen 真实输出）。"""
    lines = []
    if ctx.current_topic:
        lines.append(f"- 当前话题：{ctx.current_topic}")
    emo_cn = EMOTION_CN.get(ctx.emotion, ctx.emotion)
    if ctx.emotion and ctx.emotion != "neutral":
        strength = "比较" if ctx.emotion_intensity >= 0.6 else "有点"
        lines.append(f"- 情绪：{emo_cn}（{strength}强烈，{ctx.emotion_intensity:.1f}）")
    scene_cn = SCENE_CN.get(ctx.scene, ctx.scene)
    if ctx.scene and ctx.scene != "conversation":
        lines.append(f"- 场景：{scene_cn}")
    need_cn = NEED_CN.get(ctx.need, "")
    if need_cn:
        lines.append(f"- 此刻可能需要的：{need_cn}")
    if not lines:
        return ""
    return "\n\n".join(["【当前情境分析】", "\n".join(lines)])


def _safety_block(ctx) -> str:
    directive = getattr(ctx, "safety_directive", "")
    return f"\n\n{directive}" if directive else ""


def _policy_block(ctx) -> str:
    """陪伴策略决策 + 推荐内容，作为生成阶段的强指令。

    关键：让不同动作产生可感知的文本差异——
    - recommend_* 动作：必须在回复中明确带出推荐项（歌名/故事/游戏）
    - 倾听/共情类动作：明确禁止塞推荐，专注共情本身
    """
    decision = getattr(ctx, "decision", None)
    if decision is None:
        return ""
    lines = [f"- 本轮陪伴动作：{decision.action}"]
    if decision.response_style:
        lines.append(f"- 语气风格：{decision.response_style}")
    if decision.action_hint:
        lines.append(f"- 引导要求：{decision.action_hint}")
    if not decision.should_continue_conversation:
        lines.append("- 本轮以安抚为主，不要追问、不要展开新话题。")

    rec = getattr(ctx, "recommendation", None)
    if decision.action in ("recommend_music", "recommend_story",
                           "recommend_content") and rec:
        if "artist" in rec:  # 音乐
            lines.append(
                f"- 【必做】请在回复中自然推荐这首歌：《{rec['title']}》（{rec['artist']}），"
                f"理由：{rec.get('reason', '经典老歌')}。不要用模糊表述，要说出歌名。"
            )
        elif "summary" in rec:  # 故事
            lines.append(
                f"- 【必做】请在回复中讲这个故事的梗概：《{rec['title']}》——{rec['summary']}。"
            )
    elif decision.action in ("empathetic_chat", "continue_listening",
                             "ask_gentle_question"):
        lines.append("- 【约束】本轮不要推荐音乐/故事/游戏，专注倾听与共情，"
                     "让老人感受到你此刻只想陪他说话。")

    return "\n".join(lines)


def _long_memory_block(ctx) -> str:
    if not getattr(ctx, "long_memories", None):
        return ""
    lines = [f"- {m['content']}" for m in ctx.long_memories]
    return "【关于这位老人的长期记忆】\n" + "\n".join(lines) + \
        "\n（这些是老人过去告诉过你的事实，可自然引用；除此之外不得编造。）"


def _knowledge_block(ctx) -> str:
    """注入外部知识检索结果，并明确其可信边界。"""
    results = getattr(ctx, "knowledge_results", None) or []
    if not results:
        return ""
    lines = []
    for item in results:
        source = item.get("source") or item.get("title") or "知识库"
        lines.append(f"- [{source}] {item['content']}")
    return (
        "【知识库参考资料】\n" + "\n".join(lines) +
        "\n（仅在与老人当前问题相关时使用；资料不足时要诚实说明，不要编造，也不要向老人提及内部检索过程。）"
    )


def _elicitation_block(ctx) -> str:
    """M4：本轮允许顺带问一个关于往事的问题。

    `hint` 是**追问方向**，不是要念的稿子——必须让主模型自己化成口语问句，
    否则每次都是同一句模板，老人听得出来是机器。这里把边界写死：
    只问这一个、不说"我记录到"、不逼问、老人不想聊就立刻放下。
    """
    info = getattr(ctx, "elicitation", None)
    if not info:
        return ""
    hint = (info.get("hint") or "").strip()
    if not hint:
        return ""
    return "\n".join([
        "【本轮可以顺带问一句往事】",
        f"- 想了解的方向：{hint}",
        "- 用您自己的话把它化成一句家常问句，不要照搬上面的字面措辞，"
        "也不要提\"记录\"\"回忆录\"\"档案\"这类词。",
        "- 只问这一个，问完就停，不要再接第二个问题。",
        "- 老人要是说不想提、或者把话头岔开了，顺着他就好，别追问。",
    ])


# 各长度档位的话术（2026-10-19）：默认中档即原来的"2~3 句话、60 字以内"。
# 寒暄/提醒/危机走短档，讲故事/接往事走中长档——长度由本轮内容决定，
# 见 app/agent/companion_agent.py 的 reply_max_tokens()。
LENGTH_RULE_DEFAULT = (
    "回复控制在 2~3 句话、60 字以内。老人看不了也听不了长篇大论，"
    "写得越短越好，留白让老人接话。"
)
LENGTH_RULE_SHORT = "回复控制在 1~2 句话、30 字以内，越短越好，别铺开说。"
LENGTH_RULE_LONG = (
    "这一轮可以多聊两句：展开到 4~6 句、150 字以内，把话题接展开，"
    "老人提到细节就顺着细节聊、适当追问一句；但仍要口语化，别变成长篇大论。"
)


def build_messages(ctx, user_message: str, length_rule: Optional[str] = None):
    """把 (system+画像+长期记忆+情境分析+策略+安全指令, 短期历史, 当前消息) 拼成 messages。

    length_rule：本轮的长度要求话术（按内容分档，见上方三个常量）。
    不传则用默认中档；占位符 {length_rule} 一定被替换掉，不会泄漏进 prompt。
    """
    system = COMPANION_SYSTEM_PROMPT.replace(
        "{length_rule}", length_rule or LENGTH_RULE_DEFAULT
    )

    profile_block = ctx.profile.prompt_block()
    if profile_block:
        system += "\n\n【老人画像】\n" + profile_block + \
                  "\n（以上信息是该老人在注册时主动填写的真实信息，你可以在对话中直接引用，比如称呼对方的名字、提及兴趣爱好等。不要说'我不知道你的名字'这类话。）"

    mem_block = _long_memory_block(ctx)
    if mem_block:
        system += "\n\n" + mem_block

    knowledge_block = _knowledge_block(ctx)
    if knowledge_block:
        system += "\n\n" + knowledge_block

    state_block = _state_block(ctx)
    if state_block:
        system += "\n\n" + state_block

    policy_block = _policy_block(ctx)
    if policy_block:
        system += "\n\n【陪伴策略】\n" + policy_block

    elicit_block = _elicitation_block(ctx)
    if elicit_block:
        system += "\n\n" + elicit_block

    system += _safety_block(ctx)

    messages = [{"role": "system", "content": system}]
    for role, content in ctx.history:
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return messages

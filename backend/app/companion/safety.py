"""安全策略（设计文档第二十八节）。

情感陪伴不是医疗/心理系统。当情绪分析判定 risk_level=high
（自伤、自杀念头、严重身体不适、危及生命），或命中高危关键词时，
生成阶段必须切换到"安全升级"话术：稳住情绪 + 引导联系家人/医生/紧急服务，
不做诊断、不承诺、不说教。

本模块只做"判定 + 提供安全话术片段"，最终动作仍由 CompanionPolicy 编排。
"""
import re
from typing import Tuple

# 高危关键词兜底（Qwen 已判 high 时不依赖此表；此表用于 Qwen 漏判时补刀）
_HIGH_RISK_PATTERNS = [
    r"不想活", r"活[着个]没意[思识]", r"自杀", r"不想再", r"结束[自这]", 
    r"[要想]死", r"伤害自[己我]", r"不想挣[扎脱]", r"一了百了",
    r"[喘不]不上气", r"胸[口部].*(疼|痛|闷)", r"晕倒", r"出血.*不止",
]
_HIGH_RISK_RE = re.compile("|".join(_HIGH_RISK_PATTERNS))

# 身体不适类：中等风险，提示联系家人/就医，但不算危机干预
_BODY_DISTRESS_RE = re.compile(
    r"(头疼|头晕|肚子疼|浑身疼|发烧|血压高|吃药|不舒服|难受|摔倒|骨折)"
)

SAFETY_CARE_LINE = (
    "您先别慌，我在这儿陪着您。这样的感受很重要，不该一个人扛。"
    "现在方便给最亲近的家人打个电话吗？或者拨打 120 找医生。"
)

SAFETY_MEDICAL_LINE = (
    "身体不舒服可不能拖。您身边有家人吗？建议现在就告诉他们，"
    "或者拨打 120。我陪着您，先别自己做重活。"
)


def assess_safety(message: str, qwen_risk_level: str,
                  qwen_intent: str) -> Tuple[str, str]:
    """返回 (risk_level, safety_directive)。

    risk_level: low / medium / high
    safety_directive: 空字符串表示无需特别处理；否则是给生成阶段的安全指令文本。
    """
    risk = qwen_risk_level if qwen_risk_level in ("low", "medium", "high") else "low"

    # 关键词兜底：Qwen 判低但命中高危表述，升级为 high
    if _HIGH_RISK_RE.search(message):
        risk = "high"
    elif qwen_intent == "safety_alert":
        risk = "high"

    if risk == "high":
        directive = (
            "【安全优先】老人表达了可能伤害自己或极度痛苦的内容。请：\n"
            "1. 先温和地稳住情绪，表达陪伴（不要惊慌、不要说教、不要追问细节）。\n"
            "2. 温和建议联系家人或拨打 120 / 当地急救电话。\n"
            "3. 不做任何心理疾病或医疗诊断，不承诺能替其解决问题。\n"
            "4. 语气务必平静温暖，回复控制在三句以内。\n"
            f"参考表达：{SAFETY_CARE_LINE}"
        )
        return risk, directive

    # 身体诉求但非危机：中风险，引导就医但不升级
    if risk != "high" and _BODY_DISTRESS_RE.search(message):
        if risk == "low":
            risk = "medium"
        directive = (
            "【健康提醒】老人提到身体不适。请表达关心，温和建议告诉家人或就医，"
            "不要给出具体的诊断或用药建议（例如不要说'你这是XX病''吃点XX药'）。\n"
            f"参考表达：{SAFETY_MEDICAL_LINE}"
        )
        return risk, directive

    return risk, ""

"""表情关怀话术：识别到老人情绪后，说一句贴合当下心情的话。

设计（2026-10-16，机器狗调试前的软件闭环）：
- **写死话术库为主**：老人陪护场景要的是即时、稳定、可预期——LLM 生成要 1~3 秒，
  且可能不稳定；写死话术零延迟零成本，话术本身也是打磨过的。
- 每类表情 2~3 句轮换：同一表情反复出现时不说同一句（老人会听腻），
  按 user_id 进程内轮换（重启清零，无状态依赖）。
- **播报策略**：只有"值得回应"的表情才播——
  - happy/sad/angry/fear/disgust：播（正面热情、负面安抚）；
  - neutral 不播（老人大部分时间平静，每 5 秒一句会吵死人）；
  - surprise 不播（太瞬时，容易误判）。
- LLM 升级点：`CARE_LLM_ENABLED=true` 时改用 Qwen 生成（失败自动降级写死），
  默认关闭。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# 表情 → 话术库（关怀口吻、口语化、短句，适合 TTS 朗读）
CARE_SPEECH: Dict[str, List[str]] = {
    "happy": [
        "看您笑得这么开心，我心里也亮堂堂的。",
        "您今天气色真好，一定是遇上喜事儿了，讲给我听听呗？",
        "开心就好！我陪您一起乐呵，咱再跳一个！",
    ],
    "sad": [
        "怎么啦，心里不痛快？别憋着，跟我说说。",
        "看您不太高兴，我在这儿陪您坐一会儿，不急。",
        "难过就靠一靠，我陪着您，慢慢来。",
    ],
    "angry": [
        "谁惹您生气了？别气别气，气坏了身子不值得。",
        "先深呼吸三口，我在呢，您慢慢说。",
        "别动气，咱不拿别人的错罚自己，我陪着您。",
    ],
    "fear": [
        "别怕别怕，我就在您身边呢。",
        "我在呢，什么都别怕，我陪着您。",
        "牵着我，咱们慢慢来，不怕。",
    ],
    "disgust": [
        "哪儿不舒服吗？跟我说说，我帮您想想办法。",
        "是不是闻着什么难闻的了？我陪您透透气。",
    ],
    # 平静：高频常态，只说温和的陪伴语（冷却也最长，见 COOLDOWN_BY_EMOTION）
    "neutral": [
        "我在这儿陪着您呢，您忙您的。",
        "这样安安静静待着也挺好，我守着您。",
        "您要是累了就靠一会儿，我在这儿呢。",
    ],
    "surprise": [
        "哎哟，什么事儿让您这么吃惊？跟我说说。",
        "怎么了这是？我听着呢。",
    ],
}

# 不播报的表情（当前为空：用户要求每个表情都有语音；
# 平静靠加长冷却控制频率，见 COOLDOWN_BY_EMOTION）
MUTE_REASONS: Dict[str, str] = {}

# 按表情的播报冷却（秒）：平静是常态，间隔拉长避免唠叨
COOLDOWN_BY_EMOTION: Dict[str, float] = {
    "neutral": 300.0,   # 平静：最多 5 分钟一次
    "surprise": 90.0,
}
DEFAULT_COOLDOWN = 60.0


def cooldown_for(emotion: str) -> float:
    """该表情的播报冷却秒数。"""
    return COOLDOWN_BY_EMOTION.get(emotion, DEFAULT_COOLDOWN)


# 进程内轮换索引：user_id -> {emotion: next_index}（重启清零，无持久化）
_rotation: Dict[str, Dict[str, int]] = {}


def should_speak(emotion: str) -> bool:
    """该表情是否应该播关怀话术（当前 7 类均播）。"""
    return emotion in CARE_SPEECH


def pick_canned(emotion: str, user_id: str = "") -> str:
    """写死话术库轮换取一句（同用户同表情不重复，直到轮完一圈）。"""
    lines = CARE_SPEECH[emotion]
    if len(lines) == 1:
        return lines[0]
    idx_map = _rotation.setdefault(user_id or "_", {})
    idx = idx_map.get(emotion, 0) % len(lines)
    idx_map[emotion] = idx + 1
    return lines[idx]


async def generate_care_speech(emotion: str, label_cn: str = "") -> Optional[str]:
    """LLM 生成一句关怀话（CARE_LLM_ENABLED=true 时用）；失败返回 None 走降级。"""
    try:
        from app.llm.qwen_client import QwenClient

        client = QwenClient()
        if not client.is_configured:
            return None
        label = label_cn or emotion
        prompt = (
            f"一位老人现在看起来「{label}」。请你替一只陪伴机器狗说一句口头禅式关怀话，"
            "要求：20 字以内，口语、温暖、像家里晚辈说话；"
            "不安抚过度、不提问超过一个、不提'检测/识别/表情'这些词；"
            "只输出这句话本身，不要引号、不要解释。"
        )
        text = await client.chat(
            [{"role": "user", "content": prompt}],
            model=client.model,
            max_tokens=120,
        )
        text = (text or "").strip().strip("「」\"'")
        return text[:60] or None
    except Exception as e:  # noqa: BLE001  LLM 故障绝不阻断关怀链路
        logger.warning("关怀话术 LLM 生成失败，降级写死话术: %s", e)
        return None


async def pick_speech(emotion: str, user_id: str = "", label: str = "") -> tuple[str, str]:
    """选一句关怀话。返回 (话术, 来源：canned / llm)。

    - 不播报的表情返回 ("", "")；
    - CARE_LLM_ENABLED=true 时优先 LLM，失败/超时降级写死。
    """
    if not should_speak(emotion):
        return "", ""

    from app.config import get_settings

    settings = get_settings()
    if settings.care_llm_enabled:
        text = await generate_care_speech(emotion, label)
        if text:
            return text, "llm"
        logger.info("关怀话术降级为写死库 emotion=%s", emotion)

    return pick_canned(emotion, user_id), "canned"

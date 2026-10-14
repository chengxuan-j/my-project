"""长期记忆写入判断：调用 Qwen API 分析本轮对话是否包含值得长期记住的信息。

对应设计文档第十三节：不保存所有对话，由 Qwen 输出
{ "should_save": bool, "memory_type": str, "memory": str, "importance": float }
分析失败时静默降级（不写记忆、不影响聊天主流程）。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.llm.qwen_client import LLMError, QwenClient

logger = logging.getLogger(__name__)

ALLOWED_TYPES = {
    "family", "life_experience", "interest", "preference",
    "health", "habit", "social", "place", "general",
}

EXTRACT_SYSTEM_PROMPT = """你是老人陪伴系统的记忆管理模块。你的任务是判断老人刚刚说的话里，是否包含值得长期记住的个人事实。

值得长期记住的信息（should_save=true）：
- 家人信息（姓名、关系、近况）
- 人生经历（职业、往事、重要节点）
- 兴趣爱好（喜欢的歌手、食物、活动）
- 生活习惯与偏好（作息、交流偏好）
- 健康状况的客观自述（如"腿脚不好"）——仅记录事实，不做任何诊断
- 常联系的人、常去的地方

不应该保存（should_save=false）：
- 寒暄、天气、一次性情绪表达（"今天有点无聊"）
- 对助手说话方式的临时要求以外的情绪内容
- 含糊不清、无法核实的信息

输出要求：只输出一个 JSON 对象，不要输出其他任何文字。格式：
{"should_save": true, "memory_type": "family", "memory": "用户的女儿叫小芳", "importance": 0.9}

memory_type 只能从这些值中选：family, life_experience, interest, preference, health, habit, social, place, general
importance 是 0~1 的小数：家人/健康/重大经历 0.8~1.0，兴趣偏好 0.5~0.7，次要信息 0.3~0.5。
memory 字段用第三人称陈述事实，不超过 30 字。
如果老人一次说了多条重要信息，输出 JSON 数组，最多 3 条。
如果不需要保存，输出：{"should_save": false}"""

_JSON_RE = re.compile(r"\{.*\}|\[.*\]", re.S)


def _parse_json(text: str) -> Optional[Any]:
    """容错解析：剥掉 markdown 代码围栏，抽取首个 JSON 对象/数组。"""
    text = text.strip().strip("`")
    text = re.sub(r"^json\s*", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


class MemoryExtractor:
    """用一次独立的轻量 Qwen 调用判断是否写入长期记忆。

    与聊天生成、第 4 轮情绪分析分开调用——不把所有能力混进一个 Prompt。
    """

    def __init__(self, client: Optional[QwenClient] = None) -> None:
        self.client = client or QwenClient()

    async def extract(self, user_message: str, ai_reply: str) -> List[Dict[str, Any]]:
        """返回待写入记忆列表（可为空）。API 失败/解析失败一律返回空列表。"""
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": f"老人说：{user_message}\n助手回复：{ai_reply}"},
        ]
        try:
            raw = await self.client.chat(messages, temperature=0.0, max_tokens=300)
        except LLMError as e:
            logger.warning("记忆提取调用失败，跳过本轮长期记忆判断: %s", e)
            return []

        data = _parse_json(raw)
        if data is None:
            logger.warning("记忆提取返回非 JSON，已跳过。原文前 120 字：%s", raw[:120])
            return []
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []

        results = []
        for item in data[:3]:
            if not isinstance(item, dict) or not item.get("should_save"):
                continue
            content = str(item.get("memory", "")).strip()
            if not content:
                continue
            mtype = str(item.get("memory_type", "general"))
            if mtype not in ALLOWED_TYPES:
                mtype = "general"
            try:
                imp = float(item.get("importance", 0.5))
            except (TypeError, ValueError):
                imp = 0.5
            results.append({"memory_type": mtype, "memory": content, "importance": imp})
        return results

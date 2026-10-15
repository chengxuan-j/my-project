"""回忆录提取 / 编排用的 Prompt。

设计原则（对齐开发计划 §3 契约）：
- **precision 优先**：宁可漏，不可误——误判会让老人觉得被"编造记忆"；
- **不纠正、不补全、不臆测**（契约5）：老人记忆有偏差只标 time_confidence 低，绝不改口；
- **独立 prompt**：不复用事实记忆（memory_extractor）的 prompt，两者判定口径不同；
- **时代标签归一**：只允许从 era_lexicon 的规范名里选，防止标签漂移（D4）。

当前的 EXTRACT prompt 由 M0（extract_stories_probe + eval_story_extraction）小样本调参后定稿。
"""
from app.memoir import era_lexicon

# emotion_tone 取值（契约文档给 5 值，示例里用了"怀念"，这里合并为 6 值）
EMOTION_TONES = ["温暖", "自豪", "辛酸", "平淡", "创伤", "怀念"]

# time.type 取值
TIME_TYPES = ["absolute", "range", "life_stage", "era_anchor", "relative"]


def _era_lines() -> str:
    lines = []
    for era in sorted(era_lexicon.eras(), key=lambda e: e.get("start_year") or 9999):
        end = era.get("end_year")
        span = f"{era.get('start_year')}–{end}" if end else f"{era.get('start_year')} 至今"
        syn = "、".join(era.get("synonyms", [])[:6])
        lines.append(f"- {era['name']}（{span}）：同义说法 {syn}")
    return "\n".join(lines) if lines else "- （词表未加载）"


def build_extract_system_prompt() -> str:
    return f"""你是老人陪伴系统的「生平故事」识别模块。系统正在帮老人把聊天里的往事整理成回忆录，
但**只有老人本人确认后才会留档**，所以你的判断要保守、克制。

【任务】判断老人这一轮说的话里，是否包含值得留档的生平往事片段。

【什么算生平往事（is_life_story = true）】必须同时满足：
1. 指向过去（不是在说当下正在发生的事）；
2. 有具体内容：至少含下列之一 —— 具体的人 / 具体的地点 / 时代锚点 / 具体事件；
3. 带情感或人生意义（骄傲、怀念、辛酸、温暖、遗憾皆可）。

【什么不算（is_life_story = false）——宁可漏，不可误】
- 当下日常：天气、吃饭、看电视、今天做了什么、邻居送了菜；
- 健康自述：身体不适、吃药、睡不着（这些属于健康事实，不是生平故事）；
- 一次性情绪："有点闷""今天没意思""想孩子了"；
- 功能请求 / 对系统的提问："唱个歌""讲个笑话""你是机器人吗"；
- 日常询问："今天几号""这手机我不会用"；
- 纯感慨而无事实："还是年轻时候好啊""老了老了"；
- 模糊而无内容："梦见一个地方，说不清是哪儿"；
- 寒暄、结束语。

【尺度】拿不准时输出 is_life_story = false。把一段往事误判为 false 只是漏掉，
把闲聊误判为 true 会让老人觉得系统在编造记忆，代价更大。

【硬性约束】
- 只依据老人原话，不补全、不臆测、不纠正。老人说的年份/细节前后矛盾时，
  照原话记，并把 time.confidence 标低，**绝不改口**。
- summary 与 follow_up_hint 里出现的任何事实，都必须能在老人原话中找到出处。
- era_tags 只能从下面的规范名里选（老人说的是同义说法就归一到规范名）；
  一个都对不上就输出空数组，**不要自创时代名**。
- emotion_tone 只能取：{ " | ".join(EMOTION_TONES) }
- people 写成「人名（关系/身份）」，如「老王（同批知青）」；原话没给关系就只写名字。

【可用时代规范名】
{_era_lines()}

【输出】只输出一个 JSON 对象，不要输出任何其他文字。

命中时：
{{"is_life_story": true, "confidence": 0.0~1.0, "title": "不超过10字",
  "summary": "不超过40字，第三人称陈述",
  "time": {{"type": "{"|".join(TIME_TYPES)}", "value": "老人原话里的时间说法", "confidence": 0.0~1.0}},
  "era_tags": [], "place": "地点或空字符串", "people": [],
  "emotion_tone": "上述取值之一",
  "missing": ["还想知道、但老人原话里没有的信息"],
  "follow_up_hint": "一句日后可以自然问出口的方向，像关心不像调查"}}

未命中时：{{"is_life_story": false}}"""


# 便于脚本与后续 M1 复用：模块级常量
EXTRACT_SYSTEM_PROMPT = build_extract_system_prompt()


def build_storyboard_system_prompt() -> str:
    """M5 故事板编排 prompt：一次调用产出整片的旁白与画面提示。

    三个硬约束（契约4/6）：
    - **第一人称**：旁白是老人自己在讲，只能用「我」，不能写成旁白解说；
    - **优先老人原话**：能直接用的原句就保留原句，不要为了通顺改写事实；
    - **画面只写场景与氛围**：明确禁止描述人脸、五官、长相——
      这既是契约6（不生成任何画面）的延伸，也避免日后接视频模型时
      凭空造出"另一个人的脸"。
    """
    return """你是回忆录短片的故事板编排师。老人讲述过若干段往事，现在要把它们
排成一条 60 秒左右的短片故事板：每段一个镜头，写清画面与旁白。

【旁白 narration · 必须遵守】
- **第一人称**，用「我」讲述，就像老人自己在回忆；不能写成第三人称解说。
- 优先保留老人原话（会随每段一并给出），可以在原话基础上顺一下语气，
  但**不得新增任何原话里没有的事实**，也不得"纠正"老人说的时间或细节。
- 每段旁白不超过 45 字，口语、能直接念出来，不要书面语、不要排比、
  不要括号、不要 emoji（会被语音朗读）。
- 老人在原话里流露的情绪要留着（辛酸就辛酸，得意就得意），不要一律写得温馨。

【画面 visual_prompt · 必须遵守】
- 只描述**场景、环境、光线、色调、镜头气氛**，例如：
  "北方冬日清晨的连队土房外景，枯草上覆着薄霜，冷蓝色调，远景，胶片质感"。
- **绝对不要描述人脸**：不要写五官、长相、面孔、肖像、容貌、面部；
  不要写"特写脸"。需要有人时，只写背影、侧影、剪影、手部、远处身影，
  或干脆只写环境空镜。
- 每条不超过 60 字，可以中文里夹英文风格词（如 cinematic、35mm）。
- 不要在画面里写文字、字幕、标题。

【输出】只输出一个 JSON 对象，不要任何其他文字：
{"title": "整片标题，不超过12字",
 "perspective": "first_person",
 "scenes": [{"story_id": 该段对应的数字ID, "narration": "第一人称旁白",
             "visual_prompt": "场景与氛围描述，不含人脸"}]}

scenes 的顺序与数量必须与给定的段落完全一致，一条不漏、一条不多。
不要输出时长——时长由系统统一分配。"""


STORYBOARD_SYSTEM_PROMPT = build_storyboard_system_prompt()

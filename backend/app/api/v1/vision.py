"""视觉：老人端拍照 → 转发小智视觉服务（MCP Vision）做图像理解。

链路：老人端浏览器拍照 → 本接口 → xiaozhi-esp32-server
`POST {xiaozhi_vision_url}`（multipart: question + 图片）→ VLLM（glm-4v / qwen-vl）。

/vision/react 在此基础上加一步：根据识别出的场景，
由 Qwen 决定机器狗的应对动作，直接调 ESP-Hi 固件 /control 让狗执行。
"""
import json
import logging
import re

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.core.dependencies import get_current_account
from app.db.models import Account
from app.llm.qwen_client import LLMError, QwenClient
from app.schemas import VisionDescribeResponse, VisionReactResponse
from app.services.dog_control import ACTION_MAP, execute_actions, normalize_actions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vision", tags=["vision"])

# 与小智端 MAX_FILE_SIZE 保持一致
MAX_IMAGE_SIZE = 5 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/bmp",
    "image/tiff",
    "image/webp",
}

DEFAULT_QUESTION = "请用简单、温暖的话，向一位老人描述这张照片里有什么。"

REACT_PROMPT = """你是老人陪伴机器狗的动作导演。根据照片场景描述，决定陪伴机器狗要做的动作，并写一句说给老人听的温暖的话。

可选动作：{actions}

规则：
- 动作选 0~2 个，要贴合场景（如看到人在挥手→摇摆或鞠躬回应；看到老人伸手→握手；看到好吃的→摇摆表示开心）。
- 移动类（前进/后退/左转/右转）只在场景明确合适时选，最多 1 个。
- 没有合适动作时 actions 给空数组。
- speech 是给老人听的话，50 字以内，语气温暖，要提到小狗做了什么（没动作就只说看到的）。
- 只输出 JSON，格式：{{"actions": ["动作名"], "speech": "..."}}，不要输出任何其他内容。"""


async def _read_image(file: UploadFile) -> tuple[bytes, str]:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片为空")
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="图片超过 5MB，请重新拍摄")
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="不支持的图片格式")
    return data, content_type or "image/jpeg"


async def _describe_via_xiaozhi(data: bytes, filename: str, content_type: str, question: str) -> str:
    """把照片发给小智 MCP Vision，返回中文描述文本。"""
    settings = get_settings()

    # 小智 MCP Vision 协议：multipart 字段顺序为 question → 图片文件；
    # Client-Id: web_test_client 是小智内置的测试通道（免 token），
    # 正式环境绑定设备后改用 Bearer token（settings.xiaozhi_auth_token）。
    headers = {
        "Client-Id": "web_test_client",
        "Device-Id": settings.xiaozhi_device_id,
    }
    if settings.xiaozhi_auth_token:
        headers["Authorization"] = f"Bearer {settings.xiaozhi_auth_token}"

    try:
        async with httpx.AsyncClient(timeout=settings.vision_timeout) as client:
            resp = await client.post(
                settings.xiaozhi_vision_url,
                headers=headers,
                data={"question": question},
                files={"file": (filename, data, content_type)},
            )
    except httpx.HTTPError as e:
        logger.error("小智视觉服务不可达 url=%s: %s", settings.xiaozhi_vision_url, e)
        raise HTTPException(
            status_code=502, detail="视觉服务暂时连不上，请确认小智服务端已启动"
        )

    try:
        payload = resp.json()
    except ValueError:
        logger.error("小智视觉服务返回非 JSON: %s", resp.text[:200])
        raise HTTPException(status_code=502, detail="视觉服务返回异常")

    if resp.status_code != 200 or not payload.get("success"):
        msg = payload.get("message") or "视觉分析失败"
        logger.error("小智视觉分析失败 status=%s: %s", resp.status_code, msg)
        raise HTTPException(status_code=502, detail=f"视觉分析失败：{msg}")

    description = str(payload.get("response") or "").strip()
    if not description:
        raise HTTPException(status_code=502, detail="视觉服务没有返回描述")
    return description


async def _decide_reaction(description: str, question: str) -> tuple[list, str]:
    """让 Qwen 根据场景描述决定机器狗动作 + 给老人的话。失败降级为无动作。"""
    client = QwenClient()
    prompt = REACT_PROMPT.format(actions="、".join(ACTION_MAP.keys()))
    try:
        content = await client.chat(
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"照片场景：{description}\n老人问的是：{question}",
                },
            ],
            max_tokens=300,
        )
    except LLMError as e:
        logger.error("动作决策 LLM 调用失败: %s", e)
        return [], ""

    # 从回复中提取 JSON（容忍 markdown 代码块包裹）
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        logger.warning("动作决策回复无 JSON: %s", content[:200])
        return [], ""
    try:
        decision = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("动作决策 JSON 解析失败: %s", m.group(0)[:200])
        return [], ""

    seq = normalize_actions(decision.get("actions") or [])
    speech = str(decision.get("speech") or "").strip()
    logger.info("动作决策: %s speech=%r", [n for n, _ in seq], speech)
    return seq, speech


@router.post("/describe", response_model=VisionDescribeResponse)
async def vision_describe(
    file: UploadFile = File(...),
    question: str = Form(default=""),
    account: Account = Depends(get_current_account),
):
    data, content_type = await _read_image(file)
    q = question.strip() or DEFAULT_QUESTION
    description = await _describe_via_xiaozhi(
        data, file.filename or "photo.jpg", content_type, q
    )
    logger.info(
        "视觉描述完成 account=%s question=%r 描述长度=%d",
        account.user_id,
        q,
        len(description),
    )
    return VisionDescribeResponse(description=description, question=q)


@router.post("/react", response_model=VisionReactResponse)
async def vision_react(
    file: UploadFile = File(...),
    question: str = Form(default=""),
    account: Account = Depends(get_current_account),
):
    """拍照 → 识别场景 → 机器狗做出相应动作 → 返回描述+动作+播报语。"""
    settings = get_settings()
    data, content_type = await _read_image(file)
    q = question.strip() or DEFAULT_QUESTION

    description = await _describe_via_xiaozhi(
        data, file.filename or "photo.jpg", content_type, q
    )

    seq, speech = await _decide_reaction(description, q)
    action_names = [n for n, _ in seq]

    dog_reached = await execute_actions(
        settings.dog_base_url, seq, timeout=settings.dog_timeout
    )
    if action_names and not dog_reached:
        logger.warning("机器狗不在线，动作未送达: %s", action_names)

    if not speech:
        speech = description  # 决策失败时播报描述本身

    logger.info(
        "视觉反应完成 account=%s 动作=%s 狗在线=%s",
        account.user_id,
        action_names,
        dog_reached,
    )
    return VisionReactResponse(
        description=description,
        question=q,
        actions=action_names,
        speech=speech,
        dog_reached=dog_reached,
    )


@router.get("/status")
async def vision_status(account: Account = Depends(get_current_account)):
    """探测小智视觉服务和机器狗是否在线。"""
    settings = get_settings()
    result = {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(settings.xiaozhi_vision_url)
        result["vision_online"] = resp.status_code == 200
        result["vision_detail"] = resp.text[:200]
    except httpx.HTTPError as e:
        result["vision_online"] = False
        result["vision_detail"] = str(e)
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.dog_base_url)
        result["dog_online"] = resp.status_code < 500
        result["dog_detail"] = f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        result["dog_online"] = False
        result["dog_detail"] = str(e)
    return result

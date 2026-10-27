"""语音：TTS + ASR。"""
import asyncio
import logging
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.companion.dialects import (
    normalize_dialect,
    tts_dialect_instruction,
    tts_dialect_voice,
)
from app.core.dependencies import get_current_account
from app.db.base import get_db
from app.db.models import Account
from app.repositories.profile_repo import ProfileRepo
from app.schemas import (
    ASRResultResponse,
    ASRSubmitResponse,
    ASRTranscribeResponse,
    TTSRequest,
    TTSResponse,
)
from app.speech.speech_client import (
    ASR_CANCELED,
    ASR_FAILED,
    ASR_PENDING,
    ASR_SUCCEEDED,
    SpeechError,
    _client as speech_client,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/speech", tags=["speech"])


async def _active_dialect(session: AsyncSession, account: Account) -> str:
    """取老人当前启用的方言；没开方言/家属账号返回空串。"""
    if account.role != "elderly":
        return ""
    profile = await ProfileRepo(session).get(account.user_id)
    if profile is None:
        return ""
    prefs = profile.conversation_preferences or {}
    if not prefs.get("dialect_mode"):
        return ""
    return normalize_dialect(profile.dialect or "")


async def _effective_dialect(
    session: AsyncSession, account: Account, override: str
) -> str:
    """通话页可以临时指定方言：显式传了就优先，传空则跟随账号设置。

    「普通话」是显式要求关闭方言，不能被账号设置覆盖回去。
    """
    raw = (override or "").strip()
    if raw:
        return normalize_dialect(raw)
    return await _active_dialect(session, account)


@router.post("/tts", response_model=TTSResponse)
async def speech_tts(
    req: TTSRequest,
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    active = await _active_dialect(session, account)
    voice = tts_dialect_voice(active)
    try:
        if voice:
            # 有原生方言音色就用它，这才是真的方言播报
            url = await speech_client.synthesize_dialect(text, voice)
        else:
            # 普通话（或东北/河南这类没有方言音色的）：普通话音色 + 方言用词
            url = await speech_client.synthesize(
                text, voice=req.voice, instruction=tts_dialect_instruction(active) or None
            )
    except SpeechError as e:
        logger.warning("TTS 失败（dialect=%r voice=%r），回退普通话音色: %s", active, voice, e)
        try:
            url = await speech_client.synthesize(text, voice=req.voice)
        except SpeechError as e2:
            logger.error("TTS 回退仍失败: %s", e2)
            raise HTTPException(status_code=502, detail=str(e2))
    return TTSResponse(audio_url=url)


@router.post("/asr/submit", response_model=ASRSubmitResponse)
async def speech_asr_submit(
    file: UploadFile = File(...),
    dialect: str = Form(""),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频超过 10MB")
    # 开了方言才用 fun-asr（能听懂七大方言，但更重）；
    # 普通话/没开方言用 paraformer-v2，识别更快。
    active = await _effective_dialect(session, account, dialect)
    model = speech_client.asr_model if active else speech_client.asr_fallback_model
    try:
        oss_url = await speech_client.upload_audio(
            data, filename=file.filename or "audio.wav", model=model
        )
        task_id = await speech_client.submit_transcription(oss_url, model=model)
    except SpeechError as e:
        logger.error("ASR 提交失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    logger.info("ASR 已提交 task_id=%s model=%s dialect=%r", task_id, model, active)
    return ASRSubmitResponse(task_id=task_id, status=ASR_PENDING)


@router.post("/asr/transcribe", response_model=ASRTranscribeResponse)
async def speech_asr_transcribe(
    file: UploadFile = File(...),
    dialect: str = Form(""),
    account: Account = Depends(get_current_account),
    session: AsyncSession = Depends(get_db),
):
    """上传一段音频，直接返回识别文字（服务端合并了上传 / 提交 / 轮询）。

    「语音通话」一轮一答，如果前端自己 submit + 轮询，光 HTTP 往返就多出
    3~6 次；这里一次请求到位，通话的"说完到看见字"能少 200~400ms。
    也支持直接上传方言录音：传 dialect 就用 fun-asr 识别。
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频超过 20MB")

    active = await _effective_dialect(session, account, dialect)
    model = speech_client.asr_model if active else speech_client.asr_fallback_model
    t0 = time.perf_counter()
    try:
        oss_url = await speech_client.upload_audio(
            data, filename=file.filename or "audio.wav", model=model
        )
        task_id = await speech_client.submit_transcription(oss_url, model=model)
    except SpeechError as e:
        logger.error("通话识别提交失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))

    # 首轮几乎立刻查一次，之后逐步放宽到 0.8s；总预算 25s。
    delay = 0.2
    deadline = time.perf_counter() + 25
    while True:
        try:
            res = await speech_client.fetch_result(task_id)
        except SpeechError as e:
            logger.error("通话识别轮询失败 task_id=%s: %s", task_id, e)
            raise HTTPException(status_code=502, detail=str(e))
        status = res["status"]
        if status == ASR_SUCCEEDED or res["text"]:
            text = (res["text"] or "").strip()
            elapsed = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "通话识别完成 %.0fms model=%s dialect=%r chars=%d",
                elapsed, model, active, len(text),
            )
            return ASRTranscribeResponse(
                text=text, dialect=active, model=model, elapsed_ms=elapsed
            )
        if status in (ASR_FAILED, ASR_CANCELED):
            raise HTTPException(
                status_code=502, detail=res["error"] or "语音识别失败"
            )
        if time.perf_counter() > deadline:
            raise HTTPException(status_code=504, detail="语音识别超时，请再说一次")
        await asyncio.sleep(delay)
        delay = min(delay * 1.35, 0.8)


@router.get("/asr/{task_id}", response_model=ASRResultResponse)
async def speech_asr_result(task_id: str):
    try:
        res = await speech_client.fetch_result(task_id)
    except SpeechError as e:
        logger.error("ASR 查询失败 task_id=%s: %s", task_id, e)
        raise HTTPException(status_code=502, detail=str(e))
    return ASRResultResponse(
        task_id=task_id,
        status=res["status"],
        text=res["text"],
        error=res["error"],
    )

"""语音：TTS + ASR。"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.dependencies import get_current_account
from app.db.models import Account
from app.schemas import ASRResultResponse, ASRSubmitResponse, TTSRequest, TTSResponse
from app.speech.speech_client import ASR_PENDING, SpeechError, _client as speech_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/speech", tags=["speech"])


@router.post("/tts", response_model=TTSResponse)
async def speech_tts(
    req: TTSRequest,
    account: Account = Depends(get_current_account),
):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本不能为空")
    try:
        url = await speech_client.synthesize(text, voice=req.voice)
    except SpeechError as e:
        logger.error("TTS 失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    return TTSResponse(audio_url=url)


@router.post("/asr/submit", response_model=ASRSubmitResponse)
async def speech_asr_submit(
    file: UploadFile = File(...),
    account: Account = Depends(get_current_account),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="音频为空")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="音频超过 10MB")
    try:
        oss_url = await speech_client.upload_audio(
            data, filename=file.filename or "audio.wav"
        )
        task_id = await speech_client.submit_transcription(oss_url)
    except SpeechError as e:
        logger.error("ASR 提交失败: %s", e)
        raise HTTPException(status_code=502, detail=str(e))
    logger.info("ASR 已提交 task_id=%s", task_id)
    return ASRSubmitResponse(task_id=task_id, status=ASR_PENDING)


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

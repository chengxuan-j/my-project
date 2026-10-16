import time
import json
import uuid
import random
import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.connection import ConnectionHandler
from core.device_registry import register_device
from core.utils.dialogue import Message
from core.utils.util import audio_to_data
from core.providers.tts.dto.dto import SentenceType
from core.utils.wakeup_word import WakeupWordsConfig
from core.handle.sendAudioHandle import sendAudioMessage, send_tts_message
from core.utils.util import remove_punctuation_and_length, opus_datas_to_wav_bytes
from core.providers.tools.device_mcp import MCPClient, send_mcp_initialize_message

TAG = __name__

WAKEUP_CONFIG = {
    "refresh_time": 10,
    "responses": [
        "我一直都在呢，您请说。",
        "在的呢，请随时吩咐我。",
        "来啦来啦，请告诉我吧。",
        "您请说，我正听着。",
        "请您讲话，我准备好了。",
        "请您说出指令吧。",
        "我认真听着呢，请讲。",
        "请问您需要什么帮助？",
        "我在这里，等候您的指令。",
    ],
}

# 创建全局的唤醒词配置管理器
wakeup_words_config = WakeupWordsConfig()

# 用于防止并发调用wakeupWordsResponse的锁
_wakeup_response_lock = asyncio.Lock()


def _rebuild_opus_encoder(conn) -> None:
    """按 conn.sample_rate 重建 TTS 的 opus 编码器（采样率与设备不一致时调用）。

    TTS 的编码器只在 open_audio_channels 时按当时的 conn.sample_rate 创建一次，
    之后不随 hello 更新——所以采样率变了必须重建，否则编码/解码不一致。
    """
    try:
        tts = getattr(conn, "tts", None)
        if tts is None:
            return  # TTS 还没初始化，后续 open_audio_channels 会用新采样率创建
        from core.utils import opus_encoder_utils

        tts.opus_encoder = opus_encoder_utils.OpusEncoderUtils(
            sample_rate=conn.sample_rate, channels=1, frame_size_ms=60
        )
        conn.logger.bind(tag=TAG).info("opus 编码器已按新采样率重建")
    except Exception as e:  # noqa: BLE001
        conn.logger.bind(tag=TAG).warning(f"重建 opus 编码器失败: {e}")


async def handleHelloMessage(conn: "ConnectionHandler", msg_json):
    """处理hello消息"""
    audio_params = msg_json.get("audio_params")
    if audio_params:
        format = audio_params.get("format")
        conn.logger.bind(tag=TAG).debug(f"客户端音频格式: {format}")
        conn.audio_format = format
        conn.welcome_msg["audio_params"] = audio_params

        # 同步输出采样率（2026-10-16 修）：连接初始化时 conn.sample_rate 用的是配置
        # 默认值（24000），而设备可能声明 16000——不同步的话 opus 编码器按 24k 编码，
        # 设备按 16k 解码 → 播放异常/无声（实测 ESP-Hi 声明 16000）。
        try:
            sr = int(audio_params.get("sample_rate") or 0)
        except (TypeError, ValueError):
            sr = 0
        if sr > 0 and sr != getattr(conn, "sample_rate", None):
            conn.sample_rate = sr
            conn.logger.bind(tag=TAG).info(f"按设备声明更新输出采样率: {sr}")
            _rebuild_opus_encoder(conn)
    features = msg_json.get("features")
    if features:
        conn.logger.bind(tag=TAG).debug(f"客户端特性: {features}")
        conn.features = features
        if features.get("mcp"):
            conn.logger.bind(tag=TAG).debug("客户端支持MCP")
            conn.mcp_client = MCPClient()
        if features.get("aec"):
            conn.logger.bind(tag=TAG).debug("客户端启用了服务端AEC")
            conn.client_aec = True

    # ---- 设备识别与登记（关键修复） ----
    # 真实 ESP32 固件把 device_id 放在握手后的 hello 消息里，而非 HTTP 头/URL 查询参数。
    # 之前服务端既不解析也不登记，导致 /devices 永远为空、HTTP /say 永远找不到设备，
    # 狗因此"在线却不出声"。这里解析出真实 device_id 并登记到全局设备注册表。
    hello_device_id = (
        msg_json.get("device_id")
        or msg_json.get("deviceId")
        or msg_json.get("mac_address")
    )
    if hello_device_id:
        conn.device_id = str(hello_device_id)
    # 兜底：若本次 hello 仍未携带设备 ID，用客户端 IP 生成一个稳定 ID，
    # 保证 /devices 非空、可被 /say 主动寻址（单台狗场景完全够用）。
    if not conn.device_id:
        conn.device_id = f"dog_{conn.client_ip}"
    register_device(conn.device_id, conn)
    conn.logger.bind(tag=TAG).info(f"设备已登记到注册表: device_id={conn.device_id}")

    await conn.websocket.send(json.dumps(conn.welcome_msg))

    # The device waits for the server hello before processing MCP messages.
    if features and features.get("mcp"):
        asyncio.create_task(send_mcp_initialize_message(conn))


async def checkWakeupWords(conn: "ConnectionHandler", text):
    enable_wakeup_words_response_cache = conn.config[
        "enable_wakeup_words_response_cache"
    ]

    # 等待tts初始化，最多等待3秒
    start_time = time.time()
    while time.time() - start_time < 3:
        if conn.tts:
            break
        await asyncio.sleep(0.1)
    else:
        return False

    if not enable_wakeup_words_response_cache:
        return False

    _, filtered_text = remove_punctuation_and_length(text)
    if filtered_text not in conn.config.get("wakeup_words"):
        return False

    conn.just_woken_up = True
    await send_tts_message(conn, "start")

    # 获取当前音色
    voice = getattr(conn.tts, "voice", "default")
    if not voice:
        voice = "default"

    # 获取唤醒词回复配置
    response = wakeup_words_config.get_wakeup_response(voice)
    if not response or not response.get("file_path"):
        response = {
            "voice": "default",
            "file_path": "config/assets/wakeup_words_short.wav",
            "time": 0,
            "text": "我在这里哦！",
        }

    # 获取音频数据
    opus_packets = await audio_to_data(response.get("file_path"), use_cache=False)
    # 播放唤醒词回复
    conn.client_abort = False

    # 将唤醒词回复视为新会话，生成新的 sentence_id，确保流控器重置
    conn.sentence_id = str(uuid.uuid4().hex)

    conn.logger.bind(tag=TAG).info(f"播放唤醒词回复: {response.get('text')}")
    await sendAudioMessage(conn, SentenceType.FIRST, opus_packets, response.get("text"))
    await sendAudioMessage(conn, SentenceType.LAST, [], None)

    # 补充对话
    conn.dialogue.put(Message(role="assistant", content=response.get("text")))

    # 检查是否需要更新唤醒词回复
    if time.time() - response.get("time", 0) > WAKEUP_CONFIG["refresh_time"]:
        if not _wakeup_response_lock.locked():
            asyncio.create_task(wakeupWordsResponse(conn))
    return True


async def wakeupWordsResponse(conn: "ConnectionHandler"):
    if not conn.tts:
        return

    try:
        # 尝试获取锁，如果获取不到就返回
        if not await _wakeup_response_lock.acquire():
            return

        # 从预定义回复列表中随机选择一个回复
        result = random.choice(WAKEUP_CONFIG["responses"])
        if not result or len(result) == 0:
            return

        # 生成TTS音频
        tts_result = await asyncio.to_thread(conn.tts.to_tts, result)
        if not tts_result:
            return

        # 获取当前音色
        voice = getattr(conn.tts, "voice", "default")

        # 使用链接的sample_rate
        wav_bytes = opus_datas_to_wav_bytes(tts_result, sample_rate=conn.sample_rate)
        file_path = wakeup_words_config.generate_file_path(voice)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        # 更新配置
        wakeup_words_config.update_wakeup_response(voice, file_path, result)
    finally:
        # 确保在任何情况下都释放锁
        if _wakeup_response_lock.locked():
            _wakeup_response_lock.release()

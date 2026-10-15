"""面部表情识别服务：封装 DeepFace（ONNX 后端，本地离线推理）。

链路：老人端摄像头定时抓帧 → POST /api/v1/emotion/face → 本服务识别
→ 情绪记录入库 + SSE 推送（老人端叠加显示、家属端实时状态）。

设计约束：
- deepface 属于重依赖（首次 import + 模型构建要数秒），因此懒加载：
  后端没装 deepface 时其余功能完全不受影响，接口层收到 FaceEmotionError 再降级报错；
- 推理是 CPU 阻塞的，调用方走 async 接口，内部 asyncio.to_thread；
- 进程内一次只跑一路推理（asyncio.Lock 串行），防止多端同时抓帧把 CPU 打满；
- 同时维护每个用户"最近的表情状态"（最新结果、同一表情连续次数、上次反应时间），
  供机器狗"表情持续 5 秒才反应"的触发和聊天 Agent 上下文共用。
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# DeepFace 7 类表情 → 中文（推送与前端展示用）
EMOTION_LABEL_CN: Dict[str, str] = {
    "angry": "生气",
    "disgust": "厌恶",
    "fear": "害怕",
    "happy": "开心",
    "sad": "难过",
    "surprise": "惊讶",
    "neutral": "平静",
}

# 同一表情连续识别多少次触发狗反应：前端 5 秒一帧，
# 连续 2 次相同 ≈ 表情持续 5 秒
EMOTION_STREAK_TRIGGER = 2

# 两次狗反应之间的最小间隔（秒），避免反复打扰
REACTION_COOLDOWN = 60.0

# 识别结果多久内算"当前表情"，供聊天 Agent 参考
FRESH_SECONDS = 5 * 60


def label_cn(emotion: str) -> str:
    return EMOTION_LABEL_CN.get(emotion, emotion)


class FaceEmotionError(Exception):
    """表情识别不可用（依赖缺失 / 图片解码失败等）。"""


@dataclass
class UserEmotionState:
    """每个用户的最近表情状态（进程内，重启即清零，够用即可）。"""

    emotion: str = ""
    score: float = 0.0
    ts: float = 0.0
    emotion_streak: int = 0   # 同一表情连续出现次数（间隔 5 秒）
    last_reaction_ts: float = 0.0


class FaceEmotionService:
    """DeepFace 懒加载单例；进程内串行推理。"""

    def __init__(self) -> None:
        self._analyze_fn = None  # DeepFace.analyze
        self._lock = asyncio.Lock()
        self._states: Dict[str, UserEmotionState] = {}

    # ---------- 模型 ----------

    def _ensure_model(self) -> None:
        """首次调用时 import deepface 并构建表情模型（权重已在本地则离线可用）。"""
        if self._analyze_fn is not None:
            return
        try:
            import cv2  # noqa: F401  提前暴露缺依赖，错误信息更直观
            from deepface import DeepFace
        except Exception as e:  # noqa: BLE001
            logger.error("deepface 不可用：%s", e)
            raise FaceEmotionError(
                "表情识别组件未安装（backend 目录执行 pip install deepface onnxruntime）"
            ) from e
        self._analyze_fn = DeepFace.analyze
        logger.info("FaceEmotionService 模型就绪（首次加载耗时已含）")

    # ---------- 对外接口 ----------

    async def analyze(self, image_bytes: bytes) -> Optional[Dict[str, Any]]:
        """识别一张图片中的表情。

        返回 dict（emotion/score/region/scores/face_confidence）；
        图中没有人脸时返回 None；依赖缺失 / 解码失败抛 FaceEmotionError。
        """
        async with self._lock:
            return await asyncio.to_thread(self._analyze_sync, image_bytes)

    def _analyze_sync(self, image_bytes: bytes) -> Optional[Dict[str, Any]]:
        import cv2
        import numpy as np

        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            raise FaceEmotionError("图片解码失败，请重试")

        self._ensure_model()
        try:
            faces = self._analyze_fn(
                img,
                actions=["emotion"],
                detector_backend="opencv",
                enforce_detection=False,
                align=False,
                silent=True,
            )
        except Exception as e:  # noqa: BLE001
            # enforce_detection=False 下无人脸一般返回空列表而不是抛错，这里兜底
            logger.warning("deepface 推理异常：%s", e)
            return None

        if not faces:
            return None

        # enforce_detection=False 时，无脸会回退成"整图假脸"（face_confidence=0），
        # 真实检测（opencv haar）的置信度在 (0,1]，据此过滤
        faces = [f for f in faces if float(f.get("face_confidence") or 0) > 0.01]
        if not faces:
            return None

        # 多张人脸时取面积最大的（老人离摄像头最近）
        face = max(faces, key=lambda f: (f.get("region") or {}).get("w", 0)
                   * (f.get("region") or {}).get("h", 0))
        scores = face.get("emotion") or {}
        dominant = face.get("dominant_emotion") or (
            max(scores, key=scores.get) if scores else "neutral")
        return {
            "emotion": dominant,
            "score": round(float(scores.get(dominant, 0.0)), 1),
            "scores": {k: round(float(v), 1) for k, v in scores.items()},
            "region": face.get("region"),
            "face_confidence": face.get("face_confidence"),
        }

    # ---------- 状态跟踪 ----------

    def update_state(self, user_id: str, emotion: str, score: float) -> UserEmotionState:
        """记录一次识别结果，维护"同一表情连续次数"。返回更新后的状态。"""
        st = self._states.get(user_id)
        if st is None:
            st = UserEmotionState()
            self._states[user_id] = st
        if emotion == st.emotion:
            st.emotion_streak += 1
        else:
            st.emotion_streak = 1
        st.emotion = emotion
        st.score = score
        st.ts = time.time()
        return st

    def should_react(self, user_id: str) -> bool:
        """同一表情连续达到阈值（≈ 持续 5 秒）且距上次反应超过冷却时间。"""
        st = self._states.get(user_id)
        if not st or st.emotion_streak < EMOTION_STREAK_TRIGGER:
            return False
        return time.time() - st.last_reaction_ts >= REACTION_COOLDOWN

    def mark_reacted(self, user_id: str) -> None:
        st = self._states.get(user_id)
        if st:
            st.last_reaction_ts = time.time()
            st.emotion_streak = 0  # 反应后重新计数，避免冷却结束立刻又触发

    def latest(self, user_id: str, max_age: float = FRESH_SECONDS) -> Optional[Dict[str, Any]]:
        """最近的表情识别结果（超龄返回 None），供聊天 Agent 参考。"""
        st = self._states.get(user_id)
        if not st or not st.emotion:
            return None
        age = time.time() - st.ts
        if age > max_age:
            return None
        return {
            "emotion": st.emotion,
            "label_cn": label_cn(st.emotion),
            "score": st.score,
            "age_seconds": int(age),
        }


# 进程内单例：路由层与聊天 Agent 共用同一份模型与状态
face_emotion = FaceEmotionService()

"""
MediaPipe Tasks 封装：把一帧画面变成关键点 + 画好骨骼的图。

注意 mediapipe 0.10.30 起 legacy 的 mp.solutions 已经被移除，所以这里统一走
Tasks API（PoseLandmarker / HandLandmarker），模型 .task 文件首次运行自动下载。

骨架连线自己用 cv2 画，不依赖 mediapipe.tasks.python.vision.drawing_utils，
免得跟着版本改动来回折腾。
"""

import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

MODEL_URLS = {
    "pose_landmarker_lite.task": (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    ),
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    ),
}

# MediaPipe Pose 的骨架连线（0~32）
POSE_CONNECTIONS: Sequence[Tuple[int, int]] = (
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
    (9, 10), (11, 12),
    (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24),
    (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
)

HAND_CONNECTIONS: Sequence[Tuple[int, int]] = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

POSE_DRAW = (200, 150, 60)   # BGR
HAND_DRAW = (90, 170, 240)


@dataclass
class Detection:
    """一帧的识别结果。

    pose:  33 个 (x, y, z, visibility)，None 表示没检测到人
    hands: 每只手 21 个 (x, y, z)，没有则为空列表
    annotated: 已经画上骨骼的画面
    """

    pose: Optional[List[Tuple[float, float, float, float]]] = None
    hands: List[List[Tuple[float, float, float]]] = field(default_factory=list)
    annotated: Any = None


def ensure_model(filename: str, quiet: bool = False) -> str:
    """返回本地模型路径，不存在则下载。"""
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, filename)
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return path

    if filename not in MODEL_URLS:
        raise RuntimeError(f"没有为 {filename} 配置下载地址")

    if not quiet:
        print(f"首次运行，正在下载模型 {filename} ……")
    tmp = path + ".part"
    urllib.request.urlretrieve(MODEL_URLS[filename], tmp)
    os.replace(tmp, path)
    if not quiet:
        print(f"模型已保存到 {path}（{os.path.getsize(path) / 1e6:.1f} MB）")
    return path


class MediaPipeDetector:
    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        num_hands: int = 2,
        quiet: bool = False,
    ):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._ts = 0

        pose_path = ensure_model("pose_landmarker_lite.task", quiet=quiet)
        hand_path = ensure_model("hand_landmarker.task", quiet=quiet)

        self._pose = vision.PoseLandmarker.create_from_options(
            vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=pose_path),
                running_mode=vision.RunningMode.VIDEO,
                num_poses=1,
                min_pose_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
        )
        self._hands = vision.HandLandmarker.create_from_options(
            vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=hand_path),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=num_hands,
                min_hand_detection_confidence=min_detection_confidence,
                min_tracking_confidence=min_tracking_confidence,
            )
        )
        if not quiet:
            print("识别模型已就绪（PoseLandmarker + HandLandmarker）")

    # ------------------------------------------------------------------
    def process(self, frame_bgr: np.ndarray) -> Detection:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb),
        )

        # Tasks API 的 VIDEO 模式要求时间戳严格递增
        now_ms = int(time.monotonic() * 1000)
        self._ts = max(self._ts + 1, now_ms)

        pose_lm: Optional[List[Tuple[float, float, float, float]]] = None
        pose_result = self._pose.detect_for_video(mp_image, self._ts)
        raw_poses = getattr(pose_result, "pose_landmarks", None)
        if raw_poses:
            pose_lm = [
                (lm.x, lm.y, lm.z, float(getattr(lm, "visibility", 1.0) or 0.0))
                for lm in raw_poses[0]
            ]

        hands: List[List[Tuple[float, float, float]]] = []
        hand_result = self._hands.detect_for_video(mp_image, self._ts)
        for one in getattr(hand_result, "hand_landmarks", None) or []:
            # HandLandmarker 不输出 visibility，占位给 1.0
            hands.append([(lm.x, lm.y, lm.z) for lm in one])

        annotated = frame_bgr.copy()
        if pose_lm is not None:
            self._draw_skeleton(annotated, pose_lm, POSE_CONNECTIONS, POSE_DRAW)
        for hand_lm in hands:
            self._draw_skeleton(annotated, hand_lm, HAND_CONNECTIONS, HAND_DRAW)

        return Detection(pose=pose_lm, hands=hands, annotated=annotated)

    # ------------------------------------------------------------------
    @staticmethod
    def _draw_skeleton(
        frame: np.ndarray,
        landmarks: Sequence[Sequence[float]],
        connections: Sequence[Tuple[int, int]],
        color: Tuple[int, int, int],
    ) -> None:
        h, w = frame.shape[:2]

        def pt(i: int) -> Optional[Tuple[int, int]]:
            if i >= len(landmarks):
                return None
            x, y = landmarks[i][0], landmarks[i][1]
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                return None
            return int(x * w), int(y * h)

        for a, b in connections:
            pa, pb = pt(a), pt(b)
            if pa and pb:
                cv2.line(frame, pa, pb, color, 2, cv2.LINE_AA)
        for i in range(len(landmarks)):
            p = pt(i)
            if p:
                cv2.circle(frame, p, 2, (255, 255, 255), -1, cv2.LINE_AA)

    def close(self) -> None:
        for obj in (self._pose, self._hands):
            try:
                obj.close()
            except Exception:  # noqa: BLE001
                pass


def create_detector(**kwargs: Any) -> MediaPipeDetector:
    try:
        return MediaPipeDetector(**kwargs)
    except ImportError as exc:
        raise RuntimeError(
            "没装 mediapipe。先执行：\n"
            "  pip install -r requirements.txt\n"
            f"（原始错误：{exc}）"
        ) from exc

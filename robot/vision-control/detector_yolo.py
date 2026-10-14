"""
YOLO（ultralytics）检测后端 —— 和 detector.py 输出完全相同的 Detection，
所以上层规则（action_rules.py）、闸门、下发全都一行不用改。

为什么要做映射：
    YOLO11-Pose 输出 17 个 COCO 关键点，MediaPipe 输出 33 个。
    规则里用的是 MediaPipe 的索引（11/12 肩、15/16 腕、23/24 髋 …），
    所以这里把 COCO 17 点摆进 33 长的数组里，空缺位留 0（natural 地判为不可见）。

模型：yolo11n-pose.pt（6MB，首次运行自动下载），CPU 上约 55ms/帧。
"""

import os
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from detector import Detection  # 复用同一个结果结构体

# --------------------------------------------------------------------------
# COCO 17 点 -> MediaPipe 33 点索引
# 两套标注的左右都是"人自己的左右"，可以直接对应，不需要交换
# --------------------------------------------------------------------------
COCO_TO_MP: dict = {
    0: 0,    # nose
    1: 2,    # left_eye
    2: 5,    # right_eye
    3: 7,    # left_ear
    4: 8,    # right_ear
    5: 11,   # left_shoulder
    6: 12,   # right_shoulder
    7: 13,   # left_elbow
    8: 14,   # right_elbow
    9: 15,   # left_wrist
    10: 16,  # right_wrist
    11: 23,  # left_hip
    12: 24,  # right_hip
    13: 25,  # left_knee
    14: 26,  # right_knee
    15: 27,  # left_ankle
    16: 28,  # right_ankle
}

MP_INDEX_TO_COCO = {v: k for k, v in COCO_TO_MP.items()}

# 只画规则真正用得到的连线（躯干 + 双臂 + 双腿），避免画面太花
COCO_DRAW_EDGES: Sequence[Tuple[int, int]] = (
    (5, 6), (5, 7), (7, 9), (6, 8), (8, 10),   # 肩肘腕
    (5, 11), (6, 12), (11, 12),                # 躯干
    (11, 13), (13, 15), (12, 14), (14, 16),    # 腿
    (0, 5), (0, 6),                            # 头到肩
)

POSE_DRAW = (60, 170, 90)   # BGR 绿色，和 MediaPipe 后端的橙色区分开
HAND_DRAW = (90, 170, 240)


def _make_mp_layout(
    kpts: np.ndarray, w: int, h: int
) -> List[Tuple[float, float, float, float]]:
    """把 17x(x,y,conf) 的像素坐标铺成 33 个归一化 (x, y, z, visibility)。

    空缺的关键点补 (0, 0, 0, 0)，规则的 ok() 会因为 visibility 不足直接判不可见，
    不会拿假坐标去算角度。
    """
    out: List[Tuple[float, float, float, float]] = [(0.0, 0.0, 0.0, 0.0)] * 33
    for coco_i, mp_i in COCO_TO_MP.items():
        x, y, c = float(kpts[coco_i][0]), float(kpts[coco_i][1]), float(kpts[coco_i][2])
        out[mp_i] = (x / w, y / h, 0.0, c)
    return out


class YoloDetector:
    """ultralytics YOLO11-Pose 检测器。

    with_hands=True 时额外挂一个 MediaPipe HandLandmarker（YOLO 自身不输出手部
    21 点，手部手势需要它）。想纯 YOLO 跑就把 with_hands 关掉，
    此时"张掌/大拇指/剪刀手"三个手势指令不可用，全身姿势指令不受影响。
    """

    def __init__(
        self,
        model_name: str = "yolo11n-pose.pt",
        imgsz: int = 640,
        conf: float = 0.25,
        with_hands: bool = False,
        num_hands: int = 2,
        quiet: bool = False,
    ):
        from ultralytics import YOLO

        here = os.path.dirname(os.path.abspath(__file__))
        local = os.path.join(here, "models", model_name)
        self._model = YOLO(local if os.path.exists(local) else model_name)
        self._imgsz = imgsz
        self._conf = conf

        self._hands = None
        self._mp = None
        if with_hands:
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision

            from detector import ensure_model

            self._mp = mp
            self._hands = vision.HandLandmarker.create_from_options(
                vision.HandLandmarkerOptions(
                    base_options=mp_python.BaseOptions(
                        model_asset_path=ensure_model("hand_landmarker.task", quiet=quiet)
                    ),
                    running_mode=vision.RunningMode.VIDEO,
                    num_hands=num_hands,
                )
            )
        self._ts = 0
        if not quiet:
            extra = " + MediaPipe HandLandmarker" if with_hands else "（不含手部手势）"
            print(f"识别模型已就绪（YOLO11-Pose {model_name}{extra}）")

    # ------------------------------------------------------------------
    def process(self, frame_bgr: np.ndarray) -> Detection:
        h, w = frame_bgr.shape[:2]
        res = self._model(frame_bgr, imgsz=self._imgsz, conf=self._conf, verbose=False)[0]

        pose_lm: Optional[List[Tuple[float, float, float, float]]] = None
        kps = getattr(res, "keypoints", None)
        if kps is not None and len(kps) > 0:
            arr = kps.data.cpu().numpy()
            if arr.shape[0] > 0:
                pose_lm = _make_mp_layout(arr[0], w, h)

        hands: List[List[Tuple[float, float, float]]] = []
        if self._hands is not None:
            import time as _time

            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = self._mp.Image(
                image_format=self._mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(rgb),
            )
            now_ms = int(_time.monotonic() * 1000)
            self._ts = max(self._ts + 1, now_ms)
            hr = self._hands.detect_for_video(mp_image, self._ts)
            for one in getattr(hr, "hand_landmarks", None) or []:
                hands.append([(lm.x, lm.y, lm.z) for lm in one])

        annotated = frame_bgr.copy()
        if kps is not None and len(kps) > 0:
            self._draw_coco(annotated, kps.data.cpu().numpy()[0])
        for hand_lm in hands:
            from detector import HAND_CONNECTIONS, MediaPipeDetector

            MediaPipeDetector._draw_skeleton(annotated, hand_lm, HAND_CONNECTIONS, HAND_DRAW)

        return Detection(pose=pose_lm, hands=hands, annotated=annotated)

    # ------------------------------------------------------------------
    @staticmethod
    def _draw_coco(frame: np.ndarray, kpts: np.ndarray, min_conf: float = 0.35) -> None:
        h, w = frame.shape[:2]

        def pt(i: int) -> Optional[Tuple[int, int]]:
            x, y, c = kpts[i]
            if c < min_conf:
                return None
            x, y = int(x), int(y)
            if not (0 <= x < w and 0 <= y < h):
                return None
            return x, y

        for a, b in COCO_DRAW_EDGES:
            pa, pb = pt(a), pt(b)
            if pa and pb:
                cv2.line(frame, pa, pb, POSE_DRAW, 2, cv2.LINE_AA)
        for i in range(len(kpts)):
            p = pt(i)
            if p:
                cv2.circle(frame, p, 3, (255, 255, 255), -1, cv2.LINE_AA)

    def close(self) -> None:
        if self._hands is not None:
            try:
                self._hands.close()
            except Exception:  # noqa: BLE001
                pass


def create_yolo_detector(**kwargs: Any) -> YoloDetector:
    try:
        return YoloDetector(**kwargs)
    except ImportError as exc:
        raise RuntimeError(
            "没装 ultralytics。先执行：\n"
            "  pip install ultralytics\n"
            f"（原始错误：{exc}）"
        ) from exc

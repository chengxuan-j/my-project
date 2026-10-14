"""
视觉指令识别规则 —— 纯逻辑层。

刻意不 import mediapipe / cv2，这样识别规则可以脱离摄像头单独做单元自测
（见 selftest.py）。后面要调阈值、加动作，只改这个文件即可。

坐标约定：MediaPipe 归一化坐标，x / y ∈ [0, 1]，y 向下增大，原点在画面左上角。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

# --------------------------------------------------------------------------
# MediaPipe Pose 33 点索引（只列出用到的）
# --------------------------------------------------------------------------
POSE_NOSE = 0
POSE_LEFT_SHOULDER = 11
POSE_RIGHT_SHOULDER = 12
POSE_LEFT_ELBOW = 13
POSE_RIGHT_ELBOW = 14
POSE_LEFT_WRIST = 15
POSE_RIGHT_WRIST = 16
POSE_LEFT_HIP = 23
POSE_RIGHT_HIP = 24
POSE_LEFT_KNEE = 25
POSE_RIGHT_KNEE = 26
POSE_LEFT_ANKLE = 27
POSE_RIGHT_ANKLE = 28

POSE_LANDMARK_COUNT = 33

# --------------------------------------------------------------------------
# MediaPipe Hands 21 点索引
# --------------------------------------------------------------------------
HAND_WRIST = 0
HAND_THUMB_MCP = 2
HAND_THUMB_IP = 3
HAND_THUMB_TIP = 4
HAND_INDEX_MCP = 5
HAND_INDEX_PIP = 6
HAND_INDEX_TIP = 8
HAND_MIDDLE_MCP = 9
HAND_MIDDLE_PIP = 10
HAND_MIDDLE_TIP = 12
HAND_RING_PIP = 14
HAND_RING_TIP = 16
HAND_PINKY_PIP = 18
HAND_PINKY_TIP = 20

HAND_LANDMARK_COUNT = 21


# --------------------------------------------------------------------------
# 指令定义
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Action:
    """一条可以直接发给机器狗的指令。

    tool / args 必须和固件 main/boards/lceda-course-examples/eda-robot-pro/
    eda_dog_controller.cc 里注册的 MCP 工具名与参数名完全一致。
    """

    key: str  # 内部标识
    label: str  # 中文显示名（HUD / 日志）
    hint: str  # 触发姿势说明（显示在 HUD 上）
    tool: str  # MCP 工具名
    args: Dict[str, object] = field(default_factory=dict)
    color: str = "#1D9E75"  # HUD 配色（BGR hex，仅用于显示）


WALK_FORWARD = Action(
    "walk_forward", "前进", "双手高举过头", "self.dog.walk",
    {"steps": 4, "speed": 1000, "direction": 1},
)
TURN_LEFT = Action(
    "turn_left", "左转", "只举左手", "self.dog.turn",
    {"steps": 4, "speed": 2000, "direction": 1},
)
TURN_RIGHT = Action(
    "turn_right", "右转", "只举右手", "self.dog.turn",
    {"steps": 4, "speed": 2000, "direction": -1},
)
STOP = Action("stop", "停止", "双臂平举成 T 字", "self.dog.stop", {})
# ESP-Hi 无"坐下/站立"动作，方案 C 把这三个姿势手势就近映射到预设动作：
# 双手抱头→鞠躬、张开手掌→握手、竖大拇指→伸懒腰。label 用映射后的狗动作名，
# 实际 /control 报文由 emitter.HttpEmitter 按 key 翻译（对齐 robot_action.py 的 ACTION_MAP）。
SIT = Action("sit", "鞠躬", "双手抱头 / 下蹲", "self.dog.sit", {"speed": 1500})
STAND = Action("stand", "握手", "张开手掌", "self.dog.stand", {"speed": 1500})
STRETCH = Action("stretch", "伸懒腰", "竖大拇指", "self.dog.stretch", {"speed": 2000})
SHAKE = Action("shake", "摇摆", "剪刀手", "self.dog.shake", {"speed": 1000})

# HUD 上展示的姿势速查表
CHEATSHEET: List[Action] = [
    WALK_FORWARD, TURN_LEFT, TURN_RIGHT, STOP, SIT, STAND, STRETCH, SHAKE,
]


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------
def _dist(a: Sequence[float], b: Sequence[float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _angle_at(a: Sequence[float], vertex: Sequence[float], c: Sequence[float]) -> float:
    """返回 a-vertex-c 的夹角（0~180 度）。"""
    v1 = (a[0] - vertex[0], a[1] - vertex[1])
    v2 = (c[0] - vertex[0], c[1] - vertex[1])
    n1 = (v1[0] ** 2 + v1[1] ** 2) ** 0.5
    n2 = (v2[0] ** 2 + v2[1] ** 2) ** 0.5
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    cos = max(-1.0, min(1.0, cos))
    # 用 math 而不是 acos 手写，避免精度问题
    import math

    return math.degrees(math.acos(cos))


# --------------------------------------------------------------------------
# 全身姿势识别
# --------------------------------------------------------------------------
class PoseActionRecognizer:
    """把一帧 Pose 关键点映射成一个 Action（或 None = 中立位）。"""

    def __init__(
        self,
        visibility: float = 0.6,
        arm_span_ratio: float = 1.9,
        wrist_up_margin: float = 0.01,
        squat_angle: float = 140.0,
        head_close_ratio: float = 0.95,
        head_open_ratio: float = 1.15,
    ):
        self.visibility = visibility
        self.arm_span_ratio = arm_span_ratio
        self.wrist_up_margin = wrist_up_margin
        self.squat_angle = squat_angle
        self.head_close_ratio = head_close_ratio
        self.head_open_ratio = head_open_ratio

    def classify(self, lm: Optional[Sequence[Sequence[float]]]) -> Optional[Action]:
        if lm is None or len(lm) < POSE_LANDMARK_COUNT:
            return None

        def ok(i: int) -> bool:
            """可见且在画面内。

            MediaPipe 对画面外的点会外推出 [0,1] 范围的坐标，只看 visibility
            会把"手放在桌子底下"当成有效姿势，必须同时检查是否在画面内。
            """
            if lm[i][3] < self.visibility:
                return False
            x, y = lm[i][0], lm[i][1]
            return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

        # ---- 基础量 ----
        if not (ok(POSE_LEFT_SHOULDER) and ok(POSE_RIGHT_SHOULDER)):
            return None

        shoulder_y = (lm[POSE_LEFT_SHOULDER][1] + lm[POSE_RIGHT_SHOULDER][1]) / 2.0
        shoulder_w = abs(lm[POSE_RIGHT_SHOULDER][0] - lm[POSE_LEFT_SHOULDER][0])
        if shoulder_w < 1e-3:
            return None

        # 髋部不可见时用肩宽推算，保证"手是否在髋以下"仍可用
        if ok(POSE_LEFT_HIP) and ok(POSE_RIGHT_HIP):
            hip_y = (lm[POSE_LEFT_HIP][1] + lm[POSE_RIGHT_HIP][1]) / 2.0
        else:
            hip_y = shoulder_y + 1.3 * shoulder_w

        nose_ok = ok(POSE_NOSE)
        nose_y = lm[POSE_NOSE][1] if nose_ok else shoulder_y - 0.8 * shoulder_w

        def is_up(i: int) -> bool:
            return lm[i][1] < nose_y - self.wrist_up_margin

        left_up = ok(POSE_LEFT_WRIST) and is_up(POSE_LEFT_WRIST)
        right_up = ok(POSE_RIGHT_WRIST) and is_up(POSE_RIGHT_WRIST)

        def elbows_up() -> bool:
            return (
                ok(POSE_LEFT_ELBOW) and ok(POSE_RIGHT_ELBOW)
                and lm[POSE_LEFT_ELBOW][1] < shoulder_y
                and lm[POSE_RIGHT_ELBOW][1] < shoulder_y
            )

        # ---- 1) 双手抱头（双腕在头上方且靠得很近，双肘抬起）-> 坐下 ----
        if left_up and right_up:
            spread = abs(lm[POSE_LEFT_WRIST][0] - lm[POSE_RIGHT_WRIST][0])
            if spread < self.head_close_ratio * shoulder_w and elbows_up():
                return SIT
            if spread > self.head_open_ratio * shoulder_w:
                # ---- 2) 双手向两侧上方张开举起 -> 前进 ----
                return WALK_FORWARD
            # 介于两者之间是死区，宁可不动也不要猜

        # ---- 3) 只举左手（另一只手没举起来即可，允许它在画面外）-> 左转 ----
        if left_up and not right_up:
            return TURN_LEFT

        # ---- 4) 只举右手 -> 右转 ----
        if right_up and not left_up:
            return TURN_RIGHT

        # ---- 5) 双臂 T 字平举 -> 停止 ----
        if ok(POSE_LEFT_WRIST) and ok(POSE_RIGHT_WRIST):
            arm_span = abs(lm[POSE_LEFT_WRIST][0] - lm[POSE_RIGHT_WRIST][0])
            y_tol = 0.55 * shoulder_w
            level = (
                abs(lm[POSE_LEFT_WRIST][1] - shoulder_y) < y_tol
                and abs(lm[POSE_RIGHT_WRIST][1] - shoulder_y) < y_tol
            )
            if arm_span > self.arm_span_ratio * shoulder_w and level:
                return STOP

        # ---- 6) 下蹲 -> 坐下（需要膝盖/脚踝在画面内）----
        if self._is_squatting(lm):
            return SIT

        return None

    def _is_squatting(self, lm: Sequence[Sequence[float]]) -> bool:
        def ok(i: int) -> bool:
            if lm[i][3] < self.visibility:
                return False
            x, y = lm[i][0], lm[i][1]
            return 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

        angles: List[float] = []
        for hip, knee, ankle in (
            (POSE_LEFT_HIP, POSE_LEFT_KNEE, POSE_LEFT_ANKLE),
            (POSE_RIGHT_HIP, POSE_RIGHT_KNEE, POSE_RIGHT_ANKLE),
        ):
            if ok(hip) and ok(knee) and ok(ankle):
                angles.append(_angle_at(lm[hip], lm[knee], lm[ankle]))
        if not angles:
            return False
        # 要求双腿都明显弯曲，避免单腿迈步被误判
        return all(a < self.squat_angle for a in angles)


# --------------------------------------------------------------------------
# 手部手势识别
# --------------------------------------------------------------------------
class HandGestureRecognizer:
    """把一只手（或双手）的 21 个关键点映射成 Action。

    注意：这里刻意只做"手指明显伸直"的三种手势（张掌 / 大拇指 / 剪刀手），
    不做"握拳"——自然放松的手就很像握拳，会疯狂误触发。
    """

    def __init__(self, extend_ratio: float = 1.12):
        self.extend_ratio = extend_ratio

    def classify(self, hands: Sequence[Sequence[Sequence[float]]]) -> Optional[Action]:
        for hand in hands or []:
            action = self._classify_one(hand)
            if action is not None:
                return action
        return None

    def _classify_one(self, lm: Sequence[Sequence[float]]) -> Optional[Action]:
        if lm is None or len(lm) < HAND_LANDMARK_COUNT:
            return None

        wrist = lm[HAND_WRIST]

        def extended(pip: int, tip: int) -> bool:
            return _dist(lm[tip], wrist) > _dist(lm[pip], wrist) * self.extend_ratio

        index = extended(HAND_INDEX_PIP, HAND_INDEX_TIP)
        middle = extended(HAND_MIDDLE_PIP, HAND_MIDDLE_TIP)
        ring = extended(HAND_RING_PIP, HAND_RING_TIP)
        pinky = extended(HAND_PINKY_PIP, HAND_PINKY_TIP)
        # 阈值给得比四指更严：握拳时拇指横压在手指上，太松会被误判成"竖大拇指"
        thumb = _dist(lm[HAND_THUMB_TIP], wrist) > _dist(lm[HAND_THUMB_MCP], wrist) * 1.30

        # 张开手掌：四指全伸
        if index and middle and ring and pinky:
            return STAND

        # 剪刀手：食指 + 中指伸，无名指 + 小指曲
        if index and middle and not ring and not pinky:
            return SHAKE

        # 竖大拇指：拇指伸 + 四指全曲
        if thumb and not index and not middle and not ring and not pinky:
            return STRETCH

        return None

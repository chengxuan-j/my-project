"""
离线自测 —— 用合成关键点验证识别规则和指令闸门。

不需要摄像头、不需要 mediapipe，所以可以随时跑：
    python selftest.py
    python vision_dog.py --selftest
"""

import os
import sys
from typing import Dict, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import action_rules as R  # noqa: E402
from action_rules import (  # noqa: E402
    HAND_LANDMARK_COUNT,
    POSE_LANDMARK_COUNT,
    HandGestureRecognizer,
    PoseActionRecognizer,
)
from command_gate import CommandGate  # noqa: E402

Pose = Sequence[Sequence[float]]
Hand = Sequence[Sequence[float]]


# --------------------------------------------------------------------------
# 合成关键点
# --------------------------------------------------------------------------
def pose(**overrides: Sequence[float]) -> Pose:
    """默认是一个正面站姿、双臂自然下垂的人（即"中立位"）。"""
    lm = [[0.5, 0.5, 0.0, 1.0] for _ in range(POSE_LANDMARK_COUNT)]
    base: Dict[str, Sequence[float]] = {
        "nose": (0.500, 0.150, 0.0, 1.0),
        "left_shoulder": (0.420, 0.280, 0.0, 1.0),
        "right_shoulder": (0.580, 0.280, 0.0, 1.0),
        "left_elbow": (0.400, 0.420, 0.0, 1.0),
        "right_elbow": (0.600, 0.420, 0.0, 1.0),
        "left_wrist": (0.400, 0.560, 0.0, 1.0),
        "right_wrist": (0.600, 0.560, 0.0, 1.0),
        "left_hip": (0.440, 0.550, 0.0, 1.0),
        "right_hip": (0.560, 0.550, 0.0, 1.0),
        "left_knee": (0.440, 0.750, 0.0, 1.0),
        "right_knee": (0.560, 0.750, 0.0, 1.0),
        "left_ankle": (0.440, 0.950, 0.0, 1.0),
        "right_ankle": (0.560, 0.950, 0.0, 1.0),
    }
    index = {
        "nose": R.POSE_NOSE,
        "left_shoulder": R.POSE_LEFT_SHOULDER,
        "right_shoulder": R.POSE_RIGHT_SHOULDER,
        "left_elbow": R.POSE_LEFT_ELBOW,
        "right_elbow": R.POSE_RIGHT_ELBOW,
        "left_wrist": R.POSE_LEFT_WRIST,
        "right_wrist": R.POSE_RIGHT_WRIST,
        "left_hip": R.POSE_LEFT_HIP,
        "right_hip": R.POSE_RIGHT_HIP,
        "left_knee": R.POSE_LEFT_KNEE,
        "right_knee": R.POSE_RIGHT_KNEE,
        "left_ankle": R.POSE_LEFT_ANKLE,
        "right_ankle": R.POSE_RIGHT_ANKLE,
    }
    for name, value in base.items():
        lm[index[name]] = list(value)
    for name, value in overrides.items():
        if name not in index:
            raise KeyError(f"未知关键点：{name}")
        lm[index[name]] = list(value)
    return lm


def hand(curled: str = "") -> Hand:
    """构造一只手的 21 个关键点。

    curled 形如 "ring,pinky,thumb"，表示这几根弯曲，未列出的默认伸直。
    """
    lm = [[0.5, 0.6, 0.0, 1.0] for _ in range(HAND_LANDMARK_COUNT)]
    lm[R.HAND_WRIST] = [0.5, 0.8, 0.0, 1.0]

    # 每根手指: (mcp_i, pip_i, tip_i, 伸直时各点, 弯曲时的指尖)
    fingers = {
        "index": (
            R.HAND_INDEX_MCP, R.HAND_INDEX_PIP, R.HAND_INDEX_TIP,
            (0.470, 0.680), (0.465, 0.600), (0.460, 0.500), (0.465, 0.630),
        ),
        "middle": (
            R.HAND_MIDDLE_MCP, R.HAND_MIDDLE_PIP, R.HAND_MIDDLE_TIP,
            (0.500, 0.680), (0.500, 0.590), (0.500, 0.480), (0.500, 0.620),
        ),
        "ring": (
            13, R.HAND_RING_PIP, R.HAND_RING_TIP,
            (0.530, 0.680), (0.535, 0.600), (0.538, 0.510), (0.535, 0.630),
        ),
        "pinky": (
            17, R.HAND_PINKY_PIP, R.HAND_PINKY_TIP,
            (0.560, 0.690), (0.565, 0.620), (0.570, 0.550), (0.565, 0.650),
        ),
    }
    curled_set = {f.strip() for f in curled.split(",") if f.strip()}
    for name, (mcp_i, pip_i, tip_i, mcp, pip, tip_ext, tip_curl) in fingers.items():
        lm[mcp_i] = [mcp[0], mcp[1], 0.0, 1.0]
        lm[pip_i] = [pip[0], pip[1], 0.0, 1.0]
        tip = tip_curl if name in curled_set else tip_ext
        lm[tip_i] = [tip[0], tip[1], 0.0, 1.0]

    # 拇指：默认伸直，只有 "thumb" 在 curled 里才弯
    lm[1] = [0.460, 0.760, 0.0, 1.0]
    if "thumb" in curled_set:
        lm[R.HAND_THUMB_MCP] = [0.450, 0.720, 0.0, 1.0]
        lm[R.HAND_THUMB_IP] = [0.445, 0.730, 0.0, 1.0]
        lm[R.HAND_THUMB_TIP] = [0.440, 0.720, 0.0, 1.0]
    else:
        lm[R.HAND_THUMB_MCP] = [0.450, 0.720, 0.0, 1.0]
        lm[R.HAND_THUMB_IP] = [0.430, 0.680, 0.0, 1.0]
        lm[R.HAND_THUMB_TIP] = [0.410, 0.620, 0.0, 1.0]
    return lm


# --------------------------------------------------------------------------
# 用例
# --------------------------------------------------------------------------
ALL_CURLED = "index,middle,ring,pinky,thumb"

POSE_CASES = [
    ("中立站姿", pose(), None),
    (
        "双手抱头",
        pose(
            left_wrist=(0.470, 0.050, 0.0, 1.0), right_wrist=(0.530, 0.050, 0.0, 1.0),
            left_elbow=(0.360, 0.200, 0.0, 1.0), right_elbow=(0.640, 0.200, 0.0, 1.0),
        ),
        R.SIT,
    ),
    (
        "双手向两侧张开举过头",
        pose(
            left_wrist=(0.300, 0.030, 0.0, 1.0), right_wrist=(0.700, 0.030, 0.0, 1.0),
            left_elbow=(0.350, 0.160, 0.0, 1.0), right_elbow=(0.650, 0.160, 0.0, 1.0),
        ),
        R.WALK_FORWARD,
    ),
    (
        "双臂 T 字平举",
        pose(
            left_wrist=(0.100, 0.280, 0.0, 1.0), right_wrist=(0.900, 0.280, 0.0, 1.0),
            left_elbow=(0.250, 0.280, 0.0, 1.0), right_elbow=(0.750, 0.280, 0.0, 1.0),
        ),
        R.STOP,
    ),
    (
        "只举左手",
        pose(left_wrist=(0.440, 0.030, 0.0, 1.0), left_elbow=(0.430, 0.160, 0.0, 1.0)),
        R.TURN_LEFT,
    ),
    (
        "只举右手",
        pose(right_wrist=(0.560, 0.030, 0.0, 1.0), right_elbow=(0.570, 0.160, 0.0, 1.0)),
        R.TURN_RIGHT,
    ),
    (
        "左手举、右手在画面外",
        pose(
            left_wrist=(0.440, 0.030, 0.0, 1.0), left_elbow=(0.430, 0.160, 0.0, 1.0),
            right_wrist=(0.600, 1.200, 0.0, 0.2),
        ),
        R.TURN_LEFT,
    ),
    (
        "坐在桌前、双手在画面外（不应误触发）",
        pose(
            left_wrist=(0.420, 1.150, 0.0, 0.25), right_wrist=(0.580, 1.300, 0.0, 0.30),
        ),
        None,
    ),
    (
        "双手放在身前、未做任何姿势（不应误触发）",
        pose(left_wrist=(0.450, 0.600, 0.0, 1.0), right_wrist=(0.550, 0.600, 0.0, 1.0)),
        None,
    ),
    (
        "双手举过头但靠得很近、肘部未抬（死区，不应触发）",
        pose(
            left_wrist=(0.470, 0.030, 0.0, 1.0), right_wrist=(0.530, 0.030, 0.0, 1.0),
            left_elbow=(0.400, 0.400, 0.0, 1.0), right_elbow=(0.600, 0.400, 0.0, 1.0),
        ),
        None,
    ),
    (
        "下蹲",
        pose(
            nose=(0.500, 0.400, 0.0, 1.0),
            left_hip=(0.440, 0.720, 0.0, 1.0), right_hip=(0.560, 0.720, 0.0, 1.0),
            left_knee=(0.380, 0.820, 0.0, 1.0), right_knee=(0.620, 0.820, 0.0, 1.0),
            left_ankle=(0.440, 0.950, 0.0, 1.0), right_ankle=(0.560, 0.950, 0.0, 1.0),
            left_wrist=(0.430, 0.730, 0.0, 1.0), right_wrist=(0.570, 0.730, 0.0, 1.0),
        ),
        R.SIT,
    ),
    ("关键点全不可见", [[0.0, 0.0, 0.0, 0.0] for _ in range(POSE_LANDMARK_COUNT)], None),
]

HAND_CASES = [
    ("自然放松的手（不是手势）", [hand(ALL_CURLED)], None),
    ("张开手掌", [hand("thumb")], R.STAND),
    ("剪刀手", [hand("ring,pinky,thumb")], R.SHAKE),
    ("竖大拇指", [hand(ALL_CURLED.replace(",thumb", ""))], R.STRETCH),
    ("没有检测到手", [], None),
]


# --------------------------------------------------------------------------
# YOLO 后端映射测试：用 COCO 17 点坐标走一遍"映射 -> 规则"，确认指令判定一致
# --------------------------------------------------------------------------
COCO_W, COCO_H = 640, 480

_COCO_KEYS = {
    "nose": 0, "left_eye": 1, "right_eye": 2, "left_ear": 3, "right_ear": 4,
    "left_shoulder": 5, "right_shoulder": 6, "left_elbow": 7, "right_elbow": 8,
    "left_wrist": 9, "right_wrist": 10, "left_hip": 11, "right_hip": 12,
    "left_knee": 13, "right_knee": 14, "left_ankle": 15, "right_ankle": 16,
}

# 归一化坐标（和 pose() 的站姿一致），测试时再乘上画面尺寸
_COCO_BASE = {
    "nose": (0.500, 0.150), "left_eye": (0.480, 0.140), "right_eye": (0.520, 0.140),
    "left_ear": (0.460, 0.150), "right_ear": (0.540, 0.150),
    "left_shoulder": (0.420, 0.280), "right_shoulder": (0.580, 0.280),
    "left_elbow": (0.400, 0.420), "right_elbow": (0.600, 0.420),
    "left_wrist": (0.400, 0.560), "right_wrist": (0.600, 0.560),
    "left_hip": (0.440, 0.550), "right_hip": (0.560, 0.550),
    "left_knee": (0.440, 0.750), "right_knee": (0.560, 0.750),
    "left_ankle": (0.440, 0.950), "right_ankle": (0.560, 0.950),
}


def coco(conf: float = 0.9, **overrides) -> "list":
    """构造 YOLO 风格的 17x(x, y, conf) 像素坐标。"""
    kpts = []
    for name, idx in sorted(_COCO_KEYS.items(), key=lambda kv: kv[1]):
        nx, ny = _COCO_BASE[name]
        kpts.append([nx * COCO_W, ny * COCO_H, conf])
    for name, (nx, ny) in overrides.items():
        kpts[_COCO_KEYS[name]] = [nx * COCO_W, ny * COCO_H, conf]
    return kpts


def _test_yolo_mapping(failures: "list") -> None:
    """验证映射结果能驱动规则产出正确指令，且空缺位不会被捏造假坐标。"""
    try:
        from detector_yolo import _make_mp_layout  # noqa: PLC0415
    except ImportError as exc:  # 没装 cv2/numpy 时跳过，不算失败
        print(f"  [SKIP] 无法导入 detector_yolo（{exc}）")
        return

    rec = PoseActionRecognizer(visibility=0.4)  # 与 YOLO 后端默认阈值保持一致

    cases = [
        ("中立站姿", coco(), None),
        (
            "双手举起张开（YOLO 坐标系）",
            coco(left_wrist=(0.30, 0.030), right_wrist=(0.70, 0.030),
                 left_elbow=(0.34, 0.150), right_elbow=(0.66, 0.150)),
            R.WALK_FORWARD,
        ),
        (
            "只举左手",
            coco(left_wrist=(0.46, 0.030), left_elbow=(0.44, 0.150)),
            R.TURN_LEFT,
        ),
        (
            "只举右手",
            coco(right_wrist=(0.54, 0.030), right_elbow=(0.56, 0.150)),
            R.TURN_RIGHT,
        ),
        (
            "双臂 T 字平举",
            coco(left_wrist=(0.10, 0.280), right_wrist=(0.90, 0.280),
                 left_elbow=(0.25, 0.280), right_elbow=(0.75, 0.280)),
            R.STOP,
        ),
    ]

    for name, kpts, expected in cases:
        mapped = _make_mp_layout(kpts, COCO_W, COCO_H)
        got = rec.classify(mapped)
        ok = got is expected
        print(f"  [{'PASS' if ok else 'FAIL'}] {name:<26} -> {got.label if got else '中立位'}")
        if not ok:
            failures.append(
                f"YOLO 映射 {name}: 期望 {expected.label if expected else '中立位'}，"
                f"实际 {got.label if got else '中立位'}"
            )

    # 关键点顺序不能错：右肩必须落到 MediaPipe 的 12 号位
    mapped = _make_mp_layout(coco(), COCO_W, COCO_H)
    order_ok = (
        abs(mapped[R.POSE_RIGHT_SHOULDER][0] - 0.580) < 1e-6
        and abs(mapped[R.POSE_LEFT_SHOULDER][0] - 0.420) < 1e-6
        and abs(mapped[R.POSE_LEFT_WRIST][1] - 0.560) < 1e-6
    )
    print(f"  [{'PASS' if order_ok else 'FAIL'}] 左右肩/腕索引对应正确")
    if not order_ok:
        failures.append("YOLO 映射的左右索引错位")

    # 空缺位必须是 0 可见度，绝不能拿假坐标参与角度计算
    blank_ok = all(mapped[i][3] == 0.0 for i in (17, 18, 19, 20, 21, 22, 29, 30, 31, 32))
    print(f"  [{'PASS' if blank_ok else 'FAIL'}] 未映射的关键点可见度为 0（不捏造假坐标）")
    if not blank_ok:
        failures.append("YOLO 映射给未映射的关键点填了可见度")

    # 视频边缘外推：YOLO 不会像 MediaPipe 那样给出 >1 的坐标，但规则仍需挡住
    tail = _make_mp_layout(coco(conf=0.05), COCO_W, COCO_H)
    low_ok = rec.classify(tail) is None
    print(f"  [{'PASS' if low_ok else 'FAIL'}] 低置信度关键点不触发指令")
    if not low_ok:
        failures.append("低置信度关键点仍然触发了指令")


def run() -> int:
    pose_rec = PoseActionRecognizer()
    hand_rec = HandGestureRecognizer()
    failures = []

    print("\n== 姿势识别 ==")
    for name, landmarks, expected in POSE_CASES:
        got = pose_rec.classify(landmarks)
        ok = got is expected
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name:<18} -> {got.label if got else '中立位'}")
        if not ok:
            failures.append(f"姿势 {name}: 期望 {expected.label if expected else '中立位'}，"
                            f"实际 {got.label if got else '中立位'}")

    print("\n== 手部手势 ==")
    for name, hands, expected in HAND_CASES:
        got = hand_rec.classify(hands)
        ok = got is expected
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name:<18} -> {got.label if got else '中立位'}")
        if not ok:
            failures.append(f"手势 {name}: 期望 {expected.label if expected else '中立位'}，"
                            f"实际 {got.label if got else '中立位'}")

    print("\n== YOLO 后端：COCO 17 点 -> MediaPipe 33 点映射 ==")
    _test_yolo_mapping(failures)

    print("\n== 指令闸门（边沿触发 + 冷却）==")
    gate = CommandGate(hold_frames=8, release_frames=6, cooldown_s=0.0)
    events = []
    for i in range(10):
        confirmed, progress = gate.update(R.WALK_FORWARD)
        if confirmed is not None:
            events.append(("第 %d 帧" % (i + 1), confirmed.key))
    ok1 = events == [("第 8 帧", "walk_forward")]
    print(f"  [{'PASS' if ok1 else 'FAIL'}] 持续举手 10 帧只触发 1 次 -> {events}")
    if not ok1:
        failures.append(f"闸门连续触发次数异常：{events}")

    for _ in range(6):
        gate.update(None)
    ok2 = not gate.awaiting_release
    print(f"  [{'PASS' if ok2 else 'FAIL'}] 回中立位 6 帧后解锁 -> awaiting_release={gate.awaiting_release}")
    if not ok2:
        failures.append("闸门回到中立位后没有解锁")

    second = [gate.update(R.WALK_FORWARD)[0] for _ in range(8)][-1]
    ok3 = second is R.WALK_FORWARD
    print(f"  [{'PASS' if ok3 else 'FAIL'}] 解锁后可再次触发 -> {second.key if second else None}")
    if not ok3:
        failures.append("闸门解锁后无法再次触发")

    gate2 = CommandGate(hold_frames=3, release_frames=2, cooldown_s=60.0)
    emits = sum(1 for _ in range(3) if gate2.update(R.STOP)[0] is not None)
    for _ in range(2):
        gate2.update(None)
    emits += sum(1 for _ in range(3) if gate2.update(R.STOP)[0] is not None)
    ok4 = emits == 1
    print(f"  [{'PASS' if ok4 else 'FAIL'}] 冷却期内不重复下发 -> 触发 {emits} 次")
    if not ok4:
        failures.append("冷却期内仍然重复下发")

    if failures:
        print("\n失败项：")
        for f in failures:
            print("  - " + f)
        print(f"\n自测未通过：{len(failures)} 项\n")
        return 1

    print("\n全部通过。\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

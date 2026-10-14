"""
PC 端视觉识别 Demo —— 摄像头 -> 人体姿势/手势 -> 指令（默认只打印，不真的驱动狗）

用法：
    python vision_dog.py                      # 默认摄像头，dry-run，打印将要发送的 MCP 报文
    python vision_dog.py --camera 1           # 指定摄像头序号
    python vision_dog.py --video demo.mp4     # 用视频文件代替摄像头
    python vision_dog.py --ws ws://192.168.1.30:8080/ws   # 固件改好后直接驱动真狗
    python vision_dog.py --list-actions       # 只打印姿势/指令对照表
    python vision_dog.py --selftest           # 跑离线自测（不需要摄像头）

退出：在画面上按 q
"""

import argparse
import os
import sys
import time
from typing import List, Optional, Sequence

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import action_rules as rules  # noqa: E402
from action_rules import Action  # noqa: E402
from command_gate import CommandGate  # noqa: E402
from detector import create_detector  # noqa: E402
from detector_yolo import create_yolo_detector  # noqa: E402
from emitter import DryRunEmitter, WebSocketEmitter, HttpEmitter  # noqa: E402

# 两个后端的"关键点可信阈值"默认值不一样：
# MediaPipe 的 visibility 通常接近 1，YOLO 的关键点置信度天然偏低（手腕常在 0.5~0.7），
# 直接用 0.6 会把正常动作挡掉，所以 YOLO 单独给一个更低的默认值。
DEFAULT_VIS = {"mediapipe": 0.6, "yolo": 0.4}


# --------------------------------------------------------------------------
# HUD 文字（Windows 下用系统自带中文字体，没有就退化成英文 key）
# --------------------------------------------------------------------------
class HudText:
    FONT_CANDIDATES = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/msyhl.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]

    def __init__(self) -> None:
        self._pil = None
        self._font = None
        self._font_small = None
        try:
            from PIL import Image, ImageDraw, ImageFont

            path = next((p for p in self.FONT_CANDIDATES if os.path.exists(p)), None)
            if path:
                self._pil = (Image, ImageDraw)
                self._font = ImageFont.truetype(path, 22)
                self._font_small = ImageFont.truetype(path, 16)
        except Exception:  # noqa: BLE001 - 缺字体/缺 Pillow 都退化成 ASCII
            self._pil = None

    @property
    def cjk_ok(self) -> bool:
        return self._pil is not None

    def draw(self, frame_bgr: np.ndarray, items: Sequence[tuple]) -> np.ndarray:
        """items: [(text, x, y, color_bgr, big?)]"""
        if self._pil is None:
            for text, x, y, color, big in items:
                cv2.putText(
                    frame_bgr, text.encode("ascii", "ignore").decode() or "?",
                    (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62 if big else 0.5,
                    color, 1 if big else 1, cv2.LINE_AA,
                )
            return frame_bgr

        Image, ImageDraw = self._pil
        img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(img)
        for text, x, y, color, big in items:
            rgb = (color[2], color[1], color[0])
            font = self._font if big else self._font_small
            draw.text((x, y), text, font=font, fill=rgb)
        return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def _bar(frame: np.ndarray, x: int, y: int, w: int, h: int, ratio: float, color) -> None:
    cv2.rectangle(frame, (x, y), (x + w, y + h), (210, 210, 210), -1)
    cv2.rectangle(frame, (x, y), (x + int(w * max(0.0, min(1.0, ratio))), y + h), color, -1)


def print_actions() -> None:
    print("\n触发姿势 / 手部手势  ->  机器狗指令\n" + "-" * 52)
    for a in rules.CHEATSHEET:
        args = ", ".join(f"{k}={v}" for k, v in a.args.items())
        print(f"  {a.hint:<20} -> {a.label:<4}  {a.tool}({args})")
    print("-" * 52)
    print("说明：举手类动作用全身姿势判定，优先级高于手部手势；")
    print("      手部手势请在手臂自然下垂时比出。做完一次动作要回到中立位才能再次触发。\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="电脑视觉识别 -> 机器狗指令 Demo")
    parser.add_argument("--camera", type=int, default=0, help="摄像头序号，默认 0")
    parser.add_argument("--video", default=None, help="用视频文件代替摄像头")
    parser.add_argument(
        "--backend",
        choices=["mediapipe", "yolo"],
        default="mediapipe",
        help="识别后端：mediapipe（默认，33 点，自带手部手势）或 yolo（YOLO11-Pose 17 点）",
    )
    parser.add_argument(
        "--with-hands",
        action="store_true",
        help="YOLO 后端下额外挂 MediaPipe 手部检测，恢复张掌/大拇指/剪刀手三个手势",
    )
    parser.add_argument(
        "--vis-threshold",
        type=float,
        default=None,
        help="关键点可信度阈值，不填则按后端自动取（mediapipe 0.6 / yolo 0.4）",
    )
    parser.add_argument("--ws", default=None, help="机器狗本地 WebSocket 地址，如 ws://192.168.1.30:8080/ws")
    parser.add_argument("--http", default=None, help="ESP-Hi 机器狗 HTTP 地址，如 http://10.1.56.231（优先级高于 --ws）")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--hold-frames", type=int, default=8, help="姿势需连续保持多少帧才算数")
    parser.add_argument("--cooldown", type=float, default=2.0, help="两条指令之间的最小间隔（秒）")
    parser.add_argument("--no-display", action="store_true", help="不弹窗（无显示器/远程时用）")
    parser.add_argument("--duration", type=float, default=0.0, help="自动退出时长（秒），0 = 一直跑")
    parser.add_argument("--quiet", action="store_true", help="不在控制台打印报文")
    parser.add_argument("--list-actions", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.list_actions:
        print_actions()
        return 0

    if args.selftest:
        import selftest

        return selftest.run()

    print_actions()

    # ---- 数据源 ----
    if args.video:
        if not os.path.exists(args.video):
            print(f"找不到视频文件：{args.video}")
            return 2
        cap = cv2.VideoCapture(args.video)
        source_desc = f"视频 {args.video}"
    else:
        cap = cv2.VideoCapture(args.camera, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(args.camera)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
        source_desc = f"摄像头 #{args.camera}"

    if not cap.isOpened():
        print(f"打不开 {source_desc}。换个序号试试（--camera 1），或者用 --video 喂一段录像。")
        return 2

    # ---- 识别 / 闸门 / 下发 ----
    try:
        if args.backend == "yolo":
            detector = create_yolo_detector(with_hands=args.with_hands)
        else:
            detector = create_detector()
    except RuntimeError as exc:
        print(f"初始化识别器失败：{exc}")
        return 3

    vis = args.vis_threshold if args.vis_threshold is not None else DEFAULT_VIS[args.backend]
    pose_rec = rules.PoseActionRecognizer(visibility=vis)
    hand_rec = rules.HandGestureRecognizer()
    gate = CommandGate(hold_frames=args.hold_frames, cooldown_s=args.cooldown)

    # 下发器优先级：--http > --ws > dry-run
    if args.http:
        emitter = HttpEmitter(args.http)
    elif args.ws:
        emitter = WebSocketEmitter(args.ws)
    else:
        emitter = DryRunEmitter(verbose=not args.quiet)

    hud = HudText()

    print(f"\n数据源：{source_desc}")
    backend_desc = "MediaPipe（33 点 + 手部）" if args.backend == "mediapipe" else (
        "YOLO11-Pose（17 点）" + (" + MediaPipe 手部" if args.with_hands else "，手部手势关闭")
    )
    print(f"识别后端：{backend_desc}（关键点阈值 {vis}）")
    print(f"输出：{emitter.describe()}")
    print("HUD 中文：" + ("已启用（PIL + 系统字体）" if hud.cjk_ok else "不可用，退化为英文标签"))
    print("开始识别……按 q 退出。\n")

    seq = 0
    last_action: Optional[Action] = None
    last_action_ts = 0.0
    fps_ema = 0.0
    t_start = time.monotonic()
    last_t = t_start

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("取帧结束。")
                break

            # 关键：识别用原始帧（镜像会让 MediaPipe 的左右标注和骨架对不上），
            # 只在显示时翻转。骨骼是画在原始帧上的，翻转后人和骨架仍然对齐。
            result = detector.process(frame)

            # 先判全身姿势，没有再看手部手势
            action = pose_rec.classify(result.pose)
            if action is None:
                action = hand_rec.classify(result.hands)

            confirmed, progress = gate.update(action)
            if confirmed is not None:
                seq += 1
                emitter.emit(confirmed, seq)
                last_action = confirmed
                last_action_ts = time.monotonic()

            # ---- HUD ----
            now = time.monotonic()
            dt = now - last_t
            last_t = now
            if dt > 0:
                fps_ema = (fps_ema * 0.9 + (1.0 / dt) * 0.1) if fps_ema else (1.0 / dt)

            display = cv2.flip(result.annotated, 1)
            base_y = 28
            items: List[tuple] = []

            if action is None:
                cur_text = "中立位"
                cur_color = (120, 120, 120)
            else:
                cur_text = action.label + f"（{action.hint}）"
                cur_color = (0, 140, 70) if progress >= 1.0 else (0, 170, 220)

            items.append((f"当前判定：{cur_text}", 12, base_y, cur_color, True))
            _bar(display, 12, base_y + 10, 240, 8, progress, cur_color)

            if gate.awaiting_release:
                tip = "姿势已触发 · 请放下手回到中立位"
            elif gate.cooldown_left() > 0:
                tip = f"冷却中 {gate.cooldown_left():.1f}s"
            else:
                tip = "就绪"
            items.append((f"状态：{tip}", 12, base_y + 26, (90, 90, 90), False))

            if last_action is not None:
                age = time.monotonic() - last_action_ts
                items.append(
                    (f"最近指令：#{seq} {last_action.label} -> {last_action.tool}（{age:.0f}s 前）",
                     12, base_y + 50, (0, 90, 160), False)
                )

            items.append((f"{source_desc} | {fps_ema:4.1f} fps | {emitter.describe()}", 12, base_y + 74, (120, 120, 120), False))

            display = hud.draw(display, items)

            # 右下角姿势速查
            h, w = display.shape[:2]
            y = h - 16 * len(rules.CHEATSHEET) - 12
            for a in rules.CHEATSHEET:
                cv2.putText(display, f"{a.hint} -> {a.label}", (w - 230, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 140, 140), 1, cv2.LINE_AA)
                y += 16

            if not args.no_display:
                cv2.imshow("vision_dog", display)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if args.duration > 0 and (now - t_start) >= args.duration:
                print(f"达到 --duration {args.duration}s，退出。")
                break
    except KeyboardInterrupt:
        print("\n手动中断。")
    finally:
        cap.release()
        emitter.close()
        if not args.no_display:
            cv2.destroyAllWindows()

    print(f"\n本次共发出 {seq} 条指令。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

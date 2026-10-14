"""
用**静态图片**验证整条识别链路（不需要摄像头、不需要真人站在镜头前）。

作用和 selftest.py 的区别：
  - selftest.py 用**手写的关键点**测规则逻辑，只能证明"规则算得对"
  - probe_image.py 跑**真实推理**（MediaPipe / YOLO），把图片变成关键点再喂给规则，
    能证明"图片 -> 检测 -> 规则 -> MCP 报文"整条链路是通的

用法：
    python probe_image.py _proof/xxx.jpg                # 默认 MediaPipe 后端
    python probe_image.py --backend yolo _proof/*.jpg   # 换 YOLO 后端
    python probe_image.py --save-annotated out/ a.jpg   # 同时把画好骨骼的图存下来
"""

import argparse
import glob
import json
import os
import sys
from typing import List

import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import action_rules as rules  # noqa: E402
from emitter import build_tools_call  # noqa: E402

DEFAULT_VIS = {"mediapipe": 0.6, "yolo": 0.4}


def _make_detector(backend: str, with_hands: bool, quiet: bool = True):
    if backend == "yolo":
        from detector_yolo import create_yolo_detector

        return create_yolo_detector(with_hands=with_hands, quiet=quiet)
    from detector import create_detector

    return create_detector(quiet=quiet)


def probe_one(detector, pose_rec, hand_rec, path: str, save_dir: str = None) -> bool:
    frame = cv2.imread(path)
    if frame is None:
        print(f"  [跳过] 读不出图片：{path}")
        return False

    result = detector.process(frame)

    n_pose = len(result.pose) if result.pose else 0
    # 只统计可信的关键点，YOLO 映射后在空缺位补的是 0 可见度
    vis_th = getattr(pose_rec, "visibility", 0.5)
    strong = sum(1 for p in (result.pose or []) if p[3] >= vis_th)

    action = pose_rec.classify(result.pose)
    source = "全身姿势"
    if action is None:
        action = hand_rec.classify(result.hands)
        source = "手部手势"

    print(f"  图片      : {os.path.basename(path)}  ({frame.shape[1]}x{frame.shape[0]})")
    print(f"  关键点    : {n_pose} 个（其中 {strong} 个可信 >= {vis_th}）| 手部 {len(result.hands)} 只")

    if action is None:
        print("  判定结果  : 中立位（不触发任何指令）")
    else:
        payload = build_tools_call(action, 1)
        print(f"  判定结果  : 【{action.label}】← {action.hint}（由{source}判定）")
        print(f"  将发送报文: {json.dumps(payload, ensure_ascii=False)}")

    if save_dir:
        os.makedirs(save_dir, exist_ok=True)
        out = os.path.join(save_dir, "annotated_" + os.path.basename(path))
        cv2.imwrite(out, result.annotated)
        print(f"  骨骼图已存: {out}")

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="用静态图片验证识别链路")
    parser.add_argument("images", nargs="+", help="图片路径，支持 * 通配")
    parser.add_argument("--backend", choices=["mediapipe", "yolo"], default="mediapipe")
    parser.add_argument("--with-hands", action="store_true")
    parser.add_argument("--vis-threshold", type=float, default=None)
    parser.add_argument("--save-annotated", default=None, help="把画好骨骼的图存到这个目录")
    args = parser.parse_args()

    paths: List[str] = []
    for pat in args.images:
        paths.extend(sorted(glob.glob(pat)) or [pat])
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        print("没有找到任何图片。")
        return 2

    detector = _make_detector(args.backend, args.with_hands, quiet=True)
    vis = args.vis_threshold if args.vis_threshold is not None else DEFAULT_VIS[args.backend]
    pose_rec = rules.PoseActionRecognizer(visibility=vis)
    hand_rec = rules.HandGestureRecognizer()

    print(f"\n后端：{args.backend}（关键点阈值 {vis}）| 待验证 {len(paths)} 张图\n" + "-" * 58)
    fired = 0
    try:
        for p in paths:
            fired += 1 if probe_one(detector, pose_rec, hand_rec, p, args.save_annotated) else 0
            print()
    finally:
        detector.close()
    print("-" * 58)
    print(f"完成：{len(paths)} 张图处理完毕。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

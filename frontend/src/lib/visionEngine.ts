/**
 * 浏览器端视觉引擎 —— 移植 xiaozhi vision-control 到 TypeScript。
 *
 * 依赖：@mediapipe/tasks-vision
 * 链路：getUserMedia 视频帧 -> MediaPipe Pose/Hand -> 姿势/手势识别 ->
 *       CommandGate 防抖 -> 回调触发动作 -> POST /api/v1/dog/action
 */

import {
  FilesetResolver,
  PoseLandmarker,
  HandLandmarker,
  NormalizedLandmark,
  PoseLandmarkerResult,
  HandLandmarkerResult,
  DrawingUtils,
} from "@mediapipe/tasks-vision";

// --------------------------------------------------------------------------
// Action 定义（和 vision-control action_rules.py 对齐）
// --------------------------------------------------------------------------
export interface Action {
  key: string;
  label: string;
  hint: string;
}

const WALK_FORWARD: Action = { key: "walk_forward", label: "前进", hint: "双手高举过头" };
const TURN_LEFT: Action = { key: "turn_left", label: "左转", hint: "只举左手" };
const TURN_RIGHT: Action = { key: "turn_right", label: "右转", hint: "只举右手" };
const STOP: Action = { key: "stop", label: "停止", hint: "双臂平举成 T 字" };
const SIT: Action = { key: "sit", label: "鞠躬", hint: "双手抱头 / 下蹲" };
const STAND: Action = { key: "stand", label: "握手", hint: "张开手掌" };
const STRETCH: Action = { key: "stretch", label: "伸懒腰", hint: "竖大拇指" };
const SHAKE: Action = { key: "shake", label: "摇摆", hint: "剪刀手" };

export const CHEATSHEET: Action[] = [
  WALK_FORWARD, TURN_LEFT, TURN_RIGHT, STOP, SIT, STAND, STRETCH, SHAKE,
];

const KEY_MAP: Record<string, Action> = {
  walk_forward: WALK_FORWARD,
  turn_left: TURN_LEFT,
  turn_right: TURN_RIGHT,
  stop: STOP,
  sit: SIT,
  stand: STAND,
  stretch: STRETCH,
  shake: SHAKE,
};

// --------------------------------------------------------------------------
// MediaPipe 关键点索引（和 Python 版对齐）
// --------------------------------------------------------------------------
const POSE_NOSE = 0;
const POSE_LEFT_SHOULDER = 11;
const POSE_RIGHT_SHOULDER = 12;
const POSE_LEFT_ELBOW = 13;
const POSE_RIGHT_ELBOW = 14;
const POSE_LEFT_WRIST = 15;
const POSE_RIGHT_WRIST = 16;
const POSE_LEFT_HIP = 23;
const POSE_RIGHT_HIP = 24;
const POSE_LEFT_KNEE = 25;
const POSE_RIGHT_KNEE = 26;
const POSE_LEFT_ANKLE = 27;
const POSE_RIGHT_ANKLE = 28;

const HAND_WRIST = 0;
const HAND_THUMB_MCP = 2;
const HAND_THUMB_TIP = 4;
const HAND_INDEX_PIP = 6;
const HAND_INDEX_TIP = 8;
const HAND_MIDDLE_PIP = 10;
const HAND_MIDDLE_TIP = 12;
const HAND_RING_PIP = 14;
const HAND_RING_TIP = 16;
const HAND_PINKY_PIP = 18;
const HAND_PINKY_TIP = 20;

// --------------------------------------------------------------------------
// 小工具
// --------------------------------------------------------------------------
function _dist(a: NormalizedLandmark, b: NormalizedLandmark): number {
  return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
}

function _angleAt(
  a: NormalizedLandmark,
  vertex: NormalizedLandmark,
  c: NormalizedLandmark
): number {
  const v1 = { x: a.x - vertex.x, y: a.y - vertex.y };
  const v2 = { x: c.x - vertex.x, y: c.y - vertex.y };
  const n1 = Math.sqrt(v1.x ** 2 + v1.y ** 2);
  const n2 = Math.sqrt(v2.x ** 2 + v2.y ** 2);
  if (n1 < 1e-6 || n2 < 1e-6) return 180;
  const cos = (v1.x * v2.x + v1.y * v2.y) / (n1 * n2);
  return Math.acos(Math.max(-1, Math.min(1, cos))) * (180 / Math.PI);
}

// --------------------------------------------------------------------------
// PoseActionRecognizer（全身姿势）
// --------------------------------------------------------------------------
export class PoseActionRecognizer {
  visibility: number;
  armSpanRatio: number;
  wristUpMargin: number;
  squatAngle: number;
  headCloseRatio: number;
  headOpenRatio: number;

  constructor(opts?: Partial<typeof PoseActionRecognizer.prototype>) {
    this.visibility = opts?.visibility ?? 0.6;
    this.armSpanRatio = opts?.armSpanRatio ?? 1.9;
    this.wristUpMargin = opts?.wristUpMargin ?? 0.01;
    this.squatAngle = opts?.squatAngle ?? 140;
    this.headCloseRatio = opts?.headCloseRatio ?? 0.95;
    this.headOpenRatio = opts?.headOpenRatio ?? 1.15;
  }

  classify(pose: NormalizedLandmark[] | undefined): Action | null {
    if (!pose || pose.length < 33) return null;
    const lm = pose;

    const ok = (i: number) => {
      if (lm[i].visibility < this.visibility) return false;
      const { x, y } = lm[i];
      return x >= 0 && x <= 1 && y >= 0 && y <= 1;
    };

    if (!ok(POSE_LEFT_SHOULDER) || !ok(POSE_RIGHT_SHOULDER)) return null;

    const shoulderY = (lm[POSE_LEFT_SHOULDER].y + lm[POSE_RIGHT_SHOULDER].y) / 2;
    const shoulderW = Math.abs(lm[POSE_RIGHT_SHOULDER].x - lm[POSE_LEFT_SHOULDER].x);
    if (shoulderW < 1e-3) return null;

    const hipY =
      ok(POSE_LEFT_HIP) && ok(POSE_RIGHT_HIP)
        ? (lm[POSE_LEFT_HIP].y + lm[POSE_RIGHT_HIP].y) / 2
        : shoulderY + 1.3 * shoulderW;

    const noseOk = ok(POSE_NOSE);
    const noseY = noseOk ? lm[POSE_NOSE].y : shoulderY - 0.8 * shoulderW;

    const isUp = (i: number) => lm[i].y < noseY - this.wristUpMargin;

    const leftUp = ok(POSE_LEFT_WRIST) && isUp(POSE_LEFT_WRIST);
    const rightUp = ok(POSE_RIGHT_WRIST) && isUp(POSE_RIGHT_WRIST);

    const elbowsUp = () =>
      ok(POSE_LEFT_ELBOW) &&
      ok(POSE_RIGHT_ELBOW) &&
      lm[POSE_LEFT_ELBOW].y < shoulderY &&
      lm[POSE_RIGHT_ELBOW].y < shoulderY;

    // 1) 双手抱头 -> 鞠躬
    if (leftUp && rightUp) {
      const spread = Math.abs(lm[POSE_LEFT_WRIST].x - lm[POSE_RIGHT_WRIST].x);
      if (spread < this.headCloseRatio * shoulderW && elbowsUp()) return SIT;
      if (spread > this.headOpenRatio * shoulderW) return WALK_FORWARD;
    }

    // 3) 只举左手 -> 左转
    if (leftUp && !rightUp) return TURN_LEFT;
    // 4) 只举右手 -> 右转
    if (rightUp && !leftUp) return TURN_RIGHT;

    // 5) 双臂 T 字平举 -> 停止
    if (ok(POSE_LEFT_WRIST) && ok(POSE_RIGHT_WRIST)) {
      const armSpan = Math.abs(lm[POSE_LEFT_WRIST].x - lm[POSE_RIGHT_WRIST].x);
      const yTol = 0.55 * shoulderW;
      const level =
        Math.abs(lm[POSE_LEFT_WRIST].y - shoulderY) < yTol &&
        Math.abs(lm[POSE_RIGHT_WRIST].y - shoulderY) < yTol;
      if (armSpan > this.armSpanRatio * shoulderW && level) return STOP;
    }

    // 6) 下蹲 -> 鞠躬
    if (this._isSquatting(lm)) return SIT;

    return null;
  }

  private _isSquatting(lm: NormalizedLandmark[]): boolean {
    const ok = (i: number) => {
      if (lm[i].visibility < this.visibility) return false;
      const { x, y } = lm[i];
      return x >= 0 && x <= 1 && y >= 0 && y <= 1;
    };
    const angles: number[] = [];
    const pairs = [
      [POSE_LEFT_HIP, POSE_LEFT_KNEE, POSE_LEFT_ANKLE],
      [POSE_RIGHT_HIP, POSE_RIGHT_KNEE, POSE_RIGHT_ANKLE],
    ];
    for (const [hip, knee, ankle] of pairs) {
      if (ok(hip) && ok(knee) && ok(ankle)) {
        angles.push(_angleAt(lm[hip], lm[knee], lm[ankle]));
      }
    }
    if (!angles.length) return false;
    return angles.every((a) => a < this.squatAngle);
  }
}

// --------------------------------------------------------------------------
// HandGestureRecognizer（手部手势）
// --------------------------------------------------------------------------
export class HandGestureRecognizer {
  extendRatio: number;

  constructor(extendRatio = 1.12) {
    this.extendRatio = extendRatio;
  }

  classify(hands: NormalizedLandmark[][] | undefined): Action | null {
    if (!hands) return null;
    for (const hand of hands) {
      const action = this._classifyOne(hand);
      if (action) return action;
    }
    return null;
  }

  private _classifyOne(lm: NormalizedLandmark[]): Action | null {
    if (!lm || lm.length < 21) return null;
    const wrist = lm[HAND_WRIST];

    const extended = (pip: number, tip: number) =>
      _dist(lm[tip], wrist) > _dist(lm[pip], wrist) * this.extendRatio;

    const index = extended(HAND_INDEX_PIP, HAND_INDEX_TIP);
    const middle = extended(HAND_MIDDLE_PIP, HAND_MIDDLE_TIP);
    const ring = extended(HAND_RING_PIP, HAND_RING_TIP);
    const pinky = extended(HAND_PINKY_PIP, HAND_PINKY_TIP);
    const thumb =
      _dist(lm[HAND_THUMB_TIP], wrist) > _dist(lm[HAND_THUMB_MCP], wrist) * 1.3;

    if (index && middle && ring && pinky) return STAND; // 张掌 -> 握手
    if (index && middle && !ring && !pinky) return SHAKE; // 剪刀手 -> 摇摆
    if (thumb && !index && !middle && !ring && !pinky) return STRETCH; // 大拇指 -> 伸懒腰

    return null;
  }
}

// --------------------------------------------------------------------------
// CommandGate（防抖 / 边沿触发 / 冷却）
// --------------------------------------------------------------------------
export class CommandGate {
  holdFrames: number;
  releaseFrames: number;
  cooldownS: number;

  private _current: string | null = null;
  private _streak = 0;
  private _releaseStreak = 0;
  private _awaitingRelease = false;
  private _lastEmitTs = 0;

  constructor(opts?: { holdFrames?: number; releaseFrames?: number; cooldownS?: number }) {
    this.holdFrames = opts?.holdFrames ?? 8;
    this.releaseFrames = opts?.releaseFrames ?? 6;
    this.cooldownS = opts?.cooldownS ?? 2.0;
  }

  get currentKey() {
    return this._current;
  }
  get awaitingRelease() {
    return this._awaitingRelease;
  }

  cooldownLeft() {
    const left = this.cooldownS - (performance.now() / 1000 - this._lastEmitTs);
    return Math.max(0, left);
  }

  reset() {
    this._current = null;
    this._streak = 0;
    this._releaseStreak = 0;
    this._awaitingRelease = false;
    this._lastEmitTs = 0;
  }

  update(action: Action | null): { confirmed: Action | null; progress: number } {
    const now = performance.now() / 1000;

    if (action === null) {
      this._current = null;
      this._streak = 0;
      if (this._awaitingRelease) {
        this._releaseStreak++;
        if (this._releaseStreak >= this.releaseFrames) {
          this._awaitingRelease = false;
          this._releaseStreak = 0;
        }
      } else {
        this._releaseStreak = 0;
      }
      return { confirmed: null, progress: 0 };
    }

    this._releaseStreak = 0;

    if (this._current === action.key) {
      this._streak++;
    } else {
      this._current = action.key;
      this._streak = 1;
    }

    const progress = Math.min(1, this._streak / this.holdFrames);
    if (this._streak < this.holdFrames) {
      return { confirmed: null, progress };
    }

    if (this._awaitingRelease) return { confirmed: null, progress: 1 };
    if (now - this._lastEmitTs < this.cooldownS) return { confirmed: null, progress: 1 };

    this._lastEmitTs = now;
    this._awaitingRelease = true;
    return { confirmed: action, progress: 1 };
  }
}

// --------------------------------------------------------------------------
// VisionEngine（高层封装：MediaPipe 初始化 + 帧处理 + 绘制）
// --------------------------------------------------------------------------
export interface VisionEngineCallbacks {
  onAction?: (action: Action) => void;
  onStatus?: (status: { currentAction: string | null; progress: number; awaitingRelease: boolean; cooldownLeft: number }) => void;
}

export class VisionEngine {
  poseLandmarker: PoseLandmarker | null = null;
  handLandmarker: HandLandmarker | null = null;
  drawingUtils: DrawingUtils | null = null;

  poseRec = new PoseActionRecognizer();
  handRec = new HandGestureRecognizer();
  gate = new CommandGate();

  private _lastVideoTime = -1;
  private _running = false;
  private _callbacks: VisionEngineCallbacks = {};
  private _animationId = 0;

  constructor(callbacks?: VisionEngineCallbacks) {
    this._callbacks = callbacks ?? {};
  }

  async init() {
    const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");

    this.poseLandmarker = await PoseLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: "/mediapipe/models/pose_landmarker_lite.task",
        delegate: "GPU",
      },
      runningMode: "VIDEO",
      numPoses: 1,
    });

    this.handLandmarker = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: {
        modelAssetPath: "/mediapipe/models/hand_landmarker.task",
        delegate: "GPU",
      },
      runningMode: "VIDEO",
      numHands: 2,
    });

    return this;
  }

  setCallbacks(cbs: VisionEngineCallbacks) {
    this._callbacks = { ...this._callbacks, ...cbs };
  }

  start(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
    this._running = true;
    this.drawingUtils = new DrawingUtils(canvas.getContext("2d")!);

    const loop = () => {
      if (!this._running) return;
      this._processFrame(video, canvas);
      this._animationId = requestAnimationFrame(loop);
    };
    this._animationId = requestAnimationFrame(loop);
  }

  stop() {
    this._running = false;
    cancelAnimationFrame(this._animationId);
    this.gate.reset();
  }

  private _processFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement) {
    if (video.readyState < 2) return;
    if (video.currentTime === this._lastVideoTime) return;
    this._lastVideoTime = video.currentTime;

    const w = video.videoWidth;
    const h = video.videoHeight;
    canvas.width = w;
    canvas.height = h;

    const ctx = canvas.getContext("2d")!;
    ctx.clearRect(0, 0, w, h);

    // 镜像绘制（和 vision-control 的 cv2.flip 一致）
    ctx.save();
    ctx.translate(w, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(video, 0, 0, w, h);
    ctx.restore();

    // MediaPipe 检测（用未镜像的原始图像）
    const nowMs = performance.now();
    const poseResult = this.poseLandmarker!.detectForVideo(video, nowMs);
    const handResult = this.handLandmarker!.detectForVideo(video, nowMs);

    // 提取第一个人姿势
    const pose = poseResult.landmarks[0];
    const hands = handResult.landmarks;

    // 识别（姿势优先）
    let action = this.poseRec.classify(pose);
    if (!action) {
      action = this.handRec.classify(hands);
    }

    const { confirmed, progress } = this.gate.update(action);

    if (confirmed) {
      this._callbacks.onAction?.(confirmed);
    }

    this._callbacks.onStatus?.({
      currentAction: action?.label ?? null,
      progress,
      awaitingRelease: this.gate.awaitingRelease,
      cooldownLeft: this.gate.cooldownLeft(),
    });

    // 绘制骨骼（镜像绘制，和画面一致）
    if (pose) {
      ctx.save();
      ctx.translate(w, 0);
      ctx.scale(-1, 1);
      this.drawingUtils!.drawConnectors(pose, PoseLandmarker.POSE_CONNECTIONS, {
        color: "#00FF88",
        lineWidth: 3,
      });
      this.drawingUtils!.drawLandmarks(pose, {
        color: "#FF0044",
        lineWidth: 1,
        radius: 4,
      });
      ctx.restore();
    }

    if (hands) {
      ctx.save();
      ctx.translate(w, 0);
      ctx.scale(-1, 1);
      for (const hand of hands) {
        this.drawingUtils!.drawConnectors(hand, HandLandmarker.HAND_CONNECTIONS, {
          color: "#00CCFF",
          lineWidth: 2,
        });
        this.drawingUtils!.drawLandmarks(hand, {
          color: "#FFAA00",
          lineWidth: 1,
          radius: 3,
        });
      }
      ctx.restore();
    }
  }
}

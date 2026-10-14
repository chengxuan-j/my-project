// ==== 浏览器端视觉手势控制 ====
// 用 MediaPipe Tasks Vision（JS 版）在浏览器里跑姿态 + 手势识别，
// 识别到手势后经本机网页服务转发到狗的 /control。
//
// 识别规则翻译自 vision-control/action_rules.py，门控翻译自 command_gate.py。

import {
  PoseLandmarker, HandLandmarker, FilesetResolver,
} from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";

// ==== 配置 ====
const DOG_CONTROL = "/dog/control";

// MediaPipe Pose 33 点索引（只列用到的）
const NOSE = 0, L_SHOULDER = 11, R_SHOULDER = 12, L_ELBOW = 13, R_ELBOW = 14,
  L_WRIST = 15, R_WRIST = 16, L_HIP = 23, R_HIP = 24,
  L_KNEE = 25, R_KNEE = 26, L_ANKLE = 27, R_ANKLE = 28;

// Hand 21 点索引
const H_WRIST = 0, H_THUMB_MCP = 2, H_THUMB_TIP = 4,
  H_INDEX_PIP = 6, H_INDEX_TIP = 8, H_MIDDLE_PIP = 10, H_MIDDLE_TIP = 12,
  H_RING_PIP = 14, H_RING_TIP = 16, H_PINKY_PIP = 18, H_PINKY_TIP = 20;

// ==== 动作定义（key -> 显示名 + ESP-Hi /control 报文）====
// 对齐 vision-control/emitter.py 的 HttpEmitter.ACTION_MAP（方案 C）
const ACTIONS = {
  walk_forward: { label: "前进", hint: "双手高举过头", payload: { move: "F" } },
  turn_left: { label: "左转", hint: "只举左手", payload: { move: "L" } },
  turn_right: { label: "右转", hint: "只举右手", payload: { move: "R" } },
  stop: { label: "停止", hint: "双臂平举成 T 字", payload: { move: "S" } },
  sit: { label: "鞠躬", hint: "双手抱头 / 下蹲", payload: { action: "2" } },
  stand: { label: "握手", hint: "张开手掌", payload: { action: "7" } },
  stretch: { label: "伸懒腰", hint: "竖大拇指", payload: { action: "9" } },
  shake: { label: "摇摆", hint: "剪刀手", payload: { action: "4" } },
};

const MOVE_DURATION_MS = 1500;  // move 类持续时长

// ==== 几何小工具 ====
function dist(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
function angleAt(a, v, c) {
  const v1 = { x: a.x - v.x, y: a.y - v.y }, v2 = { x: c.x - v.x, y: c.y - v.y };
  const n1 = Math.hypot(v1.x, v1.y), n2 = Math.hypot(v2.x, v2.y);
  if (n1 < 1e-6 || n2 < 1e-6) return 180;
  let cos = (v1.x * v2.x + v1.y * v2.y) / (n1 * n2);
  cos = Math.max(-1, Math.min(1, cos));
  return Math.acos(cos) * 180 / Math.PI;
}

// ==== 全身姿势识别（翻译自 PoseActionRecognizer）====
const VISIBILITY = 0.6, ARM_SPAN_RATIO = 1.9, WRIST_UP_MARGIN = 0.01,
  SQUAT_ANGLE = 140, HEAD_CLOSE_RATIO = 0.95, HEAD_OPEN_RATIO = 1.15;

function classifyPose(lm) {
  // lm: 33 个 {x,y,z,visibility}
  if (!lm || lm.length < 33) return null;
  const ok = (i) => {
    if (lm[i].visibility < VISIBILITY) return false;
    const { x, y } = lm[i];
    return x >= 0 && x <= 1 && y >= 0 && y <= 1;
  };

  if (!(ok(L_SHOULDER) && ok(R_SHOULDER))) return null;
  const shoulderY = (lm[L_SHOULDER].y + lm[R_SHOULDER].y) / 2;
  const shoulderW = Math.abs(lm[R_SHOULDER].x - lm[L_SHOULDER].x);
  if (shoulderW < 1e-3) return null;

  const noseOk = ok(NOSE);
  const noseY = noseOk ? lm[NOSE].y : shoulderY - 0.8 * shoulderW;
  const isUp = (i) => lm[i].y < noseY - WRIST_UP_MARGIN;
  const leftUp = ok(L_WRIST) && isUp(L_WRIST);
  const rightUp = ok(R_WRIST) && isUp(R_WRIST);
  const elbowsUp = () => ok(L_ELBOW) && ok(R_ELBOW)
    && lm[L_ELBOW].y < shoulderY && lm[R_ELBOW].y < shoulderY;

  // 1) 双手举起：抱头->坐下(鞠躬)，张开->前进
  if (leftUp && rightUp) {
    const spread = Math.abs(lm[L_WRIST].x - lm[R_WRIST].x);
    if (spread < HEAD_CLOSE_RATIO * shoulderW && elbowsUp()) return "sit";
    if (spread > HEAD_OPEN_RATIO * shoulderW) return "walk_forward";
    // 死区不动
  }
  // 3) 只举左手 -> 左转
  if (leftUp && !rightUp) return "turn_left";
  // 4) 只举右手 -> 右转
  if (rightUp && !leftUp) return "turn_right";
  // 5) 双臂 T 字 -> 停止
  if (ok(L_WRIST) && ok(R_WRIST)) {
    const armSpan = Math.abs(lm[L_WRIST].x - lm[R_WRIST].x);
    const yTol = 0.55 * shoulderW;
    const level = Math.abs(lm[L_WRIST].y - shoulderY) < yTol
      && Math.abs(lm[R_WRIST].y - shoulderY) < yTol;
    if (armSpan > ARM_SPAN_RATIO * shoulderW && level) return "stop";
  }
  // 6) 下蹲 -> 坐下
  if (isSquatting(lm, ok)) return "sit";
  return null;
}

function isSquatting(lm, ok) {
  const angles = [];
  for (const [hip, knee, ankle] of [[L_HIP, L_KNEE, L_ANKLE], [R_HIP, R_KNEE, R_ANKLE]]) {
    if (ok(hip) && ok(knee) && ok(ankle)) angles.push(angleAt(lm[hip], lm[knee], lm[ankle]));
  }
  if (!angles.length) return false;
  return angles.every(a => a < SQUAT_ANGLE);
}

// ==== 手部手势识别（翻译自 HandGestureRecognizer）====
const EXTEND_RATIO = 1.12;
function classifyHand(hands) {
  for (const lm of hands || []) {
    const r = classifyOneHand(lm);
    if (r) return r;
  }
  return null;
}
function classifyOneHand(lm) {
  if (!lm || lm.length < 21) return null;
  const wrist = lm[H_WRIST];
  const extended = (pip, tip) => dist(lm[tip], wrist) > dist(lm[pip], wrist) * EXTEND_RATIO;
  const index = extended(H_INDEX_PIP, H_INDEX_TIP);
  const middle = extended(H_MIDDLE_PIP, H_MIDDLE_TIP);
  const ring = extended(H_RING_PIP, H_RING_TIP);
  const pinky = extended(H_PINKY_PIP, H_PINKY_TIP);
  const thumb = dist(lm[H_THUMB_TIP], wrist) > dist(lm[H_THUMB_MCP], wrist) * 1.30;
  if (index && middle && ring && pinky) return "stand";       // 张开手掌 -> 握手
  if (index && middle && !ring && !pinky) return "shake";     // 剪刀手 -> 摇摆
  if (thumb && !index && !middle && !ring && !pinky) return "stretch"; // 大拇指 -> 伸懒腰
  return null;
}

// ==== 指令闸门（翻译自 command_gate.py）====
class CommandGate {
  constructor(holdFrames = 8, releaseFrames = 6, cooldownS = 2.0) {
    this.holdFrames = holdFrames;
    this.releaseFrames = releaseFrames;
    this.cooldownS = cooldownS;
    this.reset();
  }
  reset() {
    this._current = null;
    this._streak = 0;
    this._releaseStreak = 0;
    this._awaitingRelease = false;
    this._lastEmitTs = 0;
  }
  get currentKey() { return this._current; }
  get awaitingRelease() { return this._awaitingRelease; }
  cooldownLeft() { return Math.max(0, this.cooldownS - (performance.now() / 1000 - this._lastEmitTs)); }

  update(actionKey) {
    // actionKey: string | null，返回 [确认的 key | null, 稳定进度 0~1]
    const now = performance.now() / 1000;
    if (!actionKey) {
      this._current = null; this._streak = 0;
      if (this._awaitingRelease) {
        this._releaseStreak++;
        if (this._releaseStreak >= this.releaseFrames) {
          this._awaitingRelease = false; this._releaseStreak = 0;
        }
      } else this._releaseStreak = 0;
      return [null, 0];
    }
    this._releaseStreak = 0;
    if (this._current === actionKey) this._streak++;
    else { this._current = actionKey; this._streak = 1; }
    const prog = Math.min(1, this._streak / this.holdFrames);
    if (this._streak < this.holdFrames) return [null, prog];
    if (this._awaitingRelease || now - this._lastEmitTs < this.cooldownS) return [null, 1];
    this._lastEmitTs = now; this._awaitingRelease = true;
    return [actionKey, 1];
  }
}

// ==== 下发到狗（HTTP /control）====
// 同源请求可读取真实响应，避免把网络错误误判为已送达。
async function sendControl(payload) {
  try {
    const response = await fetch(DOG_CONTROL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return response.ok && (await response.json()).code === 200;
  } catch (e) {
    return false;
  }
}

async function emit(key, onLog) {
  const act = ACTIONS[key];
  if (!act) return;
  const delivered = await sendControl(act.payload);
  onLog(`${act.label}（${act.hint}）${delivered ? "已送达" : "下发失败"}`);
  // move 类持续运动，1.5s 后补发停止
  if (delivered && act.payload.move && act.payload.move !== "S") {
    setTimeout(async () => {
      if (!(await sendControl({ move: "S" }))) onLog("停止指令下发失败");
    }, MOVE_DURATION_MS);
  }
}

// ==== 主控制器：摄像头 + 识别循环 + HUD 叠加 ====
export class VisionController {
  constructor({ video, canvas, onStatus, onLog, onProgress }) {
    this.video = video;
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onStatus = onStatus || (() => {});
    this.onLog = onLog || (() => {});
    this.onProgress = onProgress || (() => {});
    this.pose = null;
    this.hand = null;
    this.gate = new CommandGate();
    this.running = false;
    this.stream = null;
    this._raf = null;
  }

  async init() {
    this.onStatus("加载模型中…");
    const fileset = await FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm"
    );
    this.pose = await PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: "models/pose_landmarker_lite.task" },
      runningMode: "VIDEO", numPoses: 1,
    });
    this.hand = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: "models/hand_landmarker.task" },
      runningMode: "VIDEO", numHands: 2,
    });
    this.onStatus("模型就绪");
  }

  async start() {
    if (this.running) return;
    if (!this.pose) await this.init();
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480 }, audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();
    this.canvas.width = this.video.videoWidth || 640;
    this.canvas.height = this.video.videoHeight || 480;
    this.running = true;
    this.gate.reset();
    this.onStatus("识别中");
    this._loop();
  }

  stop() {
    this.running = false;
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this.stream) { this.stream.getTracks().forEach(t => t.stop()); this.stream = null; }
    this.video.srcObject = null;
    this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    this.onStatus("已停止");
    this.onProgress(0, null);
  }

  _loop() {
    if (!this.running) return;
    const ts = performance.now();
    let actionKey = null;

    const poseRes = this.pose.detectForVideo(this.video, ts);
    const poseLm = poseRes.landmarks && poseRes.landmarks[0];
    if (poseLm) actionKey = classifyPose(poseLm);

    // 全身姿势优先；没命中再看手势
    let handLmList = null;
    if (!actionKey) {
      const handRes = this.hand.detectForVideo(this.video, ts);
      handLmList = handRes.landmarks;
      if (handLmList && handLmList.length) actionKey = classifyHand(handLmList);
    }

    const [confirmed, progress] = this.gate.update(actionKey);
    this._draw(poseLm, handLmList, actionKey, progress);
    this.onProgress(progress, actionKey ? ACTIONS[actionKey]?.label : null);

    if (confirmed) emit(confirmed, this.onLog);

    this._raf = requestAnimationFrame(() => this._loop());
  }

  _draw(poseLm, handLmList, actionKey, progress) {
    const { ctx, canvas } = this;
    ctx.save();
    // 镜像绘制（和自拍一致）
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.translate(canvas.width, 0); ctx.scale(-1, 1);
    ctx.drawImage(this.video, 0, 0, canvas.width, canvas.height);

    const dot = (p, color) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p.x * canvas.width, p.y * canvas.height, 4, 0, Math.PI * 2);
      ctx.fill();
    };
    if (poseLm) for (const i of [NOSE, L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_HIP, R_HIP, L_KNEE, R_KNEE])
      if (poseLm[i] && poseLm[i].visibility >= VISIBILITY) dot(poseLm[i], "#4ade80");
    if (handLmList) for (const h of handLmList) for (const p of h) dot(p, "#f59e0b");
    ctx.restore();

    // HUD 文字（不镜像）
    if (actionKey) {
      ctx.fillStyle = "rgba(0,0,0,.55)";
      ctx.fillRect(0, 0, canvas.width, 34);
      ctx.fillStyle = "#fff"; ctx.font = "18px sans-serif";
      ctx.fillText(`${ACTIONS[actionKey].label}  ${Math.round(progress * 100)}%`, 10, 24);
    }
  }
}

export { ACTIONS };

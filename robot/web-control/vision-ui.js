// ==== 手势控制 UI 接线 ====
// 把 vision.js 的 VisionController 接到页面按钮和画布。
import { VisionController } from "./vision.js?v=dog-relay";

const camBtn = document.getElementById("camBtn");
const camWrap = document.getElementById("camWrap");
const camStatus = document.getElementById("camStatus");
const video = document.getElementById("camVideo");
const canvas = document.getElementById("camCanvas");

// 复用主对话框的日志区展示下发记录
const logEl = document.getElementById("log");
function visionLog(text) {
  const wrap = document.createElement("div");
  wrap.className = "msg sys";
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = "👋 手势：" + text;
  wrap.appendChild(b);
  logEl.appendChild(wrap);
  logEl.scrollTop = logEl.scrollHeight;
}

const controller = new VisionController({
  video, canvas,
  onStatus: (s) => { camStatus.textContent = s; },
  onLog: visionLog,
  onProgress: (p, label) => {
    if (label && p < 1) camStatus.textContent = `识别中：${label} ${Math.round(p * 100)}%`;
    else if (controller.running) camStatus.textContent = "识别中（做手势触发）";
  },
});

let on = false;
camBtn.onclick = async () => {
  if (!on) {
    try {
      camBtn.disabled = true;
      camStatus.textContent = "启动中…";
      await controller.start();
      camWrap.classList.add("show");
      camBtn.textContent = "关闭摄像头";
      camBtn.classList.add("on");
      on = true;
    } catch (e) {
      camStatus.textContent = "启动失败：" + (e.message || e);
    } finally {
      camBtn.disabled = false;
    }
  } else {
    controller.stop();
    camWrap.classList.remove("show");
    camBtn.textContent = "开启摄像头";
    camBtn.classList.remove("on");
    on = false;
  }
};

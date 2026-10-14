// ==== 配置 ====
// 网页和语音后端运行在同一台电脑；端口与 config.yaml 的 server.port 一致。
const WS_HOST = window.location.hostname + ":8001";
const DEVICE_ID = "web-ctrl-" + Math.random().toString(16).slice(2, 8);
const ACTIONS = ["前进", "后退", "左转", "右转", "鞠躬", "摇摆", "握手", "戳戳", "伸懒腰", "前跳", "收腿"];

// ==== DOM ====
const logEl = document.getElementById("log");
const dot = document.getElementById("dot");
const statusText = document.getElementById("statusText");
const dogStatus = document.getElementById("dogStatus");
const micBtn = document.getElementById("micBtn");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const quickActions = document.getElementById("quickActions");

let ws = null;
let connected = false;
let failureLogged = false;

// ==== 日志/对话展示 ====
function addMsg(text, cls) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + cls;
  const b = document.createElement("div");
  b.className = "bubble";
  b.textContent = text;
  wrap.appendChild(b);
  logEl.appendChild(wrap);
  while (logEl.children.length > 100) logEl.firstElementChild.remove();
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus(on, text) {
  connected = on;
  dot.classList.toggle("on", on);
  statusText.textContent = text;
  micBtn.disabled = !on;
}

async function checkDogStatus() {
  try {
    const response = await fetch("/dog/status", { cache: "no-store" });
    const data = await response.json();
    dogStatus.textContent = data.online
      ? `机器狗已连通 (${data.ip})`
      : `机器狗未连通 (${data.ip || "地址未知"})`;
  } catch {
    dogStatus.textContent = "机器狗状态检查不可用";
  }
}

// ==== WebSocket ====
function connect() {
  const url = `ws://${WS_HOST}/xiaozhi/v1/?device-id=${DEVICE_ID}&client-id=${DEVICE_ID}`;
  if (!failureLogged) addMsg("正在连接后端…", "sys");
  ws = new WebSocket(url);

  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    failureLogged = false;
    // 发送 hello 握手（声明音频参数，实际不发音频）
    ws.send(JSON.stringify({
      type: "hello",
      version: 1,
      transport: "websocket",
      audio_params: { format: "opus", sample_rate: 16000, channels: 1, frame_duration: 60 }
    }));
  };

  ws.onmessage = (ev) => {
    // 二进制是 TTS 音频（Opus），前端忽略，改用浏览器朗读文本
    if (typeof ev.data !== "string") return;
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    handleServerMessage(msg);
  };

  ws.onclose = () => {
    setStatus(false, "连接已断开，3秒后重连…");
    setTimeout(connect, 3000);
  };
  ws.onerror = () => {
    if (!failureLogged) addMsg("连接出错，请确认后端已启动且IP正确", "sys");
    failureLogged = true;
  };
}

function handleServerMessage(msg) {
  switch (msg.type) {
    case "hello":
      setStatus(true, `已连接后端 (设备 ${DEVICE_ID})`);
      addMsg("后端连接成功；机器狗是否在线需单独确认", "sys");
      break;
    case "stt":
      // 服务端识别到的用户输入回显（这里其实是我们发的文本）
      if (msg.text) addMsg(msg.text, "user");
      break;
    case "tts":
      // sentence_start 带 text 是模型回复的一句话
      if (msg.state === "sentence_start" && msg.text) {
        addMsg(msg.text, "bot");
        speak(msg.text);
      }
      break;
  }
}

// ==== 发送指令（走 listen/detect 文本通道 → LLM → robot_action）====
function sendText(text) {
  if (!connected || !text.trim()) return;
  ws.send(JSON.stringify({ type: "listen", state: "detect", mode: "manual", text: text.trim() }));
}

// ==== 浏览器语音合成（朗读回复）====
function speak(text) {
  if (!window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "zh-CN";
  window.speechSynthesis.speak(u);
}

// ==== 语音识别（Web Speech API，Chrome/Edge 支持）====
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizing = false;
let recognition = null;

if (SR) {
  recognition = new SR();
  recognition.lang = "zh-CN";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognizing = true;
    micBtn.classList.add("rec");
    micBtn.textContent = "🔴 正在聆听…点击停止";
  };
  recognition.onend = () => {
    recognizing = false;
    micBtn.classList.remove("rec");
    micBtn.textContent = "🎤 按住说话 / 点击开始";
  };
  recognition.onerror = (e) => {
    addMsg("语音识别出错：" + e.error, "sys");
  };
  recognition.onresult = (e) => {
    const text = e.results[0][0].transcript;
    sendText(text);
  };

  micBtn.onclick = () => {
    if (!connected) return;
    if (recognizing) { recognition.stop(); }
    else { window.speechSynthesis && window.speechSynthesis.cancel(); recognition.start(); }
  };
} else {
  micBtn.textContent = "⚠️ 浏览器不支持语音识别，请用输入框";
  micBtn.onclick = () => addMsg("请使用 Chrome 或 Edge 浏览器以启用语音识别", "sys");
}

// ==== 快捷动作按钮 ====
ACTIONS.forEach(a => {
  const btn = document.createElement("button");
  btn.textContent = a;
  btn.onclick = () => sendText(a);
  quickActions.appendChild(btn);
});

// ==== 文本输入 ====
sendBtn.onclick = () => { sendText(textInput.value); textInput.value = ""; };
textInput.addEventListener("keydown", e => {
  if (e.key === "Enter") { sendText(textInput.value); textInput.value = ""; }
});

// ==== 启动 ====
connect();
checkDogStatus();
setInterval(checkDogStatus, 10000);

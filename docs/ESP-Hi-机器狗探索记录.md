# ESP-Hi 机器狗探索记录与接管方案

> 探索时间：2026-09-23
> 设备：ESP-Hi（乐鑫 ESP Friends 开源机器狗）
> 目标：把机器狗的控制权从厂商云端迁到自己手里

---

## 一、背景

- 已入职实习：**云港陪伴新智人（廊坊）科技有限公司** —— 做具身陪伴/陪护机器人，路线是「先 IP 玩具（小黄鸭 B.Duck 桌宠/挂件/潮玩）→ 后双足仿人」
- 手边有一台基于**小智 AI** 的机器狗，可作为学习与验证硬件
- 目标：让个人项目能力向公司方向靠拢，并产出可向领导展示的成果
- 边界原则：**只用公开信息（开源代码、招聘 JD、新闻稿）**，绝不把公司内部信息写入个人仓库

---

## 二、设备档案

| 项 | 值 |
|---|---|
| 型号 | **ESP-Hi**（乐鑫 ESP Friends 开源项目） |
| 主控 | **ESP32-C3**（RISC-V 单核 160MHz，**400KB SRAM，无 PSRAM**） |
| 音频 | ADC 麦克风 + PDM 扬声器（**无外置 Codec**） |
| 显示 | 0.96 寸 SPI 彩屏（表情） |
| 舵机 | 4 路 SG92R（前左/前右/后左/后右） |
| 传感器 | 水银开关（感知晃动 → 唤醒/打断/动作） |
| 唤醒词 | "Hi, 乐鑫" |
| 电池 | 500mAh |
| 复刻成本 | 约 ¥49.9 |
| 当前局域网 IP | `192.168.31.91`（网页控制台入口） |
| 硬件开源 | https://oshwhub.com/esp-college/esp-hi （GPL-3.0） |
| 固件源码 | `78/xiaozhi-esp32` → `main/boards/espressif/esp-hi/` |

---

## 三、架构真相：端云分工

**核心结论：MCU 只做「耳朵+嘴巴+手脚+传声筒」，大脑在云端。**

| 环节 | 在哪跑 |
|---|---|
| 唤醒词检测（WakeNet） | ✅ **ESP32 本地**（离线） |
| VAD | ✅ 本地 |
| OPUS 编解码 + WebSocket 传输 | ✅ 本地 |
| 舵机 PWM / 屏幕表情 / 灯光 | ✅ 本地 |
| **ASR 语音识别** | ❌ **云端** |
| **LLM 意图理解** | ❌ **云端** |
| **TTS 合成** | ❌ **云端** |

### 为什么 ASR/LLM 不可能放本地

ESP32-C3 全部家当：400KB SRAM + 4MB Flash。
- 最小可用 ASR 模型：**几十 MB 起**
- 能对话的 LLM：**几百 MB ~ 几 GB**

**物理上塞不进去。** 跑得动的只有几百 KB 的唤醒词模型。

### 两条独立通道（关键认知）

```
通道 A：手机网页 →(局域网)→ ESP32 → 舵机/灯/屏     ← 纯本地，零 AI
通道 B：麦克风 → 唤醒 → 音频上传 → 云端 ASR/LLM/TTS → 回传  ← 必须联网
```

**A 通不代表 B 在本地。** 设备上并存两个网络组件：HTTP Server（本地，端口 80）+ WebSocket Client（出站连厂商云）。二者互不相干。

### 硬件能力天花板（源码实测）

`main/Kconfig.projbuild` 的 `WAKE_WORD_TYPE` 依赖条件：

```c
config USE_CUSTOM_WAKE_WORD          # Multinet 自定义命令词
    depends on (ESP32S3 || ESP32P4 || ESP32S31) && SPIRAM
```

**ESP-Hi 是 C3 且无 PSRAM，因此：**

| 能力 | ESP-Hi |
|---|---|
| WakeNet 唤醒词 | ✅ |
| **Multinet 本地命令词** | ❌ 用不了 |
| AFE 音频处理（AEC/VAD） | ❌ 用不了 |

→ **「本地命令词识别」这条路在这台设备上走不通**，需要换 ESP32-S3 + PSRAM 的板子。
→ 没有 AEC 意味着它说话时听不进你的声音，**无法真正打断**（网页上那个"打断"是软件层停播放）。

---

## 四、本地接口全清单（实测确认）

| 接口 | 方法 | 参数 | 作用 |
|---|---|---|---|
| `/` | GET | — | 网页控制台 |
| `/status` | GET | — | 返回 `{"listening":false}` |
| `/control` | POST | `{"action":"<id>"}` | 执行预置动作 |
| `/control` | POST | `{"move":"F\|B\|L\|R"}` | 前/后/左/右 |
| `/control` | POST | `{"wake":"on"}` | 切换对话状态（ToggleChatState） |
| `/control` | POST | `{"speed":"fast\|slow"}` | 加速模式（30s + 冷却） |
| `/control` | POST | `{"test":dir}` | 校准模式舵机测试 |
| `/start_calibration` | GET | — | 进入校准模式 |
| `/exit_calibration` | GET | — | 保存参数并退出 |
| `/adjust` | POST | — | 舵机角度调整 |

**预置动作（ID 是硬编码整数，纯查表执行，零 AI）：**

| ID | 动作 | ID | 动作 | ID | 动作 |
|---|---|---|---|---|---|
| 2 | 鞠躬 | 6 | 左右 | 9 | 伸懒腰 |
| 4 | 摇摆 | 7 | 握手 | 10 | 前跳 |
| 5 | 前后 | 8 | 戳戳 | 12 | 收腿 |

> **线索**：ID 缺 `1、3、11`，说明固件里还定义了未暴露的动作，可直接发指令试探。
> 另：HTML 里有被注释掉的「自定义动作」标签页，功能被隐藏。

**调用示例（PowerShell / Git Bash）：**

```bash
# Git Bash（真 curl）
curl -X POST http://192.168.31.91/control -H "Content-Type: application/json" -d '{"action":"7"}'

# PowerShell（用 curl.exe，或 --% 停止解析）
Invoke-RestMethod -Uri http://192.168.31.91/control -Method Post -ContentType "application/json" -Body '{"action":"7"}'
curl.exe --% -X POST http://192.168.31.91/control -H "Content-Type: application/json" -d "{\"action\":\"7\"}"
```

> ⚠️ PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，参数不兼容。必须用 `curl.exe` 或 `Invoke-RestMethod`。

---

## 五、云端协议：OTA → WebSocket（接管的关键）

### 数据流

```
设备开机
  → POST {OTA_URL}   带 device_id / board / version
  → 服务器返回 { "websocket": { "url": "ws://..." } }
  → 设备连上这个 ws://  → 音频流开始跑
```

**`websocket.url` 就是控制点** —— 你的 OTA 返回什么地址，狗就连哪里。

### 默认 OTA 地址

```
https://api.tenclass.net/xiaozhi/ota/
```

（探测确认服务器存活：`{"status":"ok","message":"Server is working normally"}`；POST 缺 device_id 会返回 `Device ID is required`）

### OTA 必须返回的结构（来自开源实现真实样例）

```json
{
  "server_time": { "timestamp": 1757567894012, "timeZone": "Asia/Shanghai", "timezone_offset": 480 },
  "activation":   { "code": "460609", "message": "...", "challenge": "11:22:33:44:55:66" },
  "firmware":     { "version": "1.0.1", "url": "http://.../NOT_ACTIVATED_..." },
  "websocket":    { "url": "ws://192.168.4.23:8000/xiaozhi/v1/" },
  "mqtt":         { "endpoint": "...:1883", "client_id": "...", "username": "...", "password": "..." }
}
```

`mqtt` 段可选（走 MQTT+UDP 协议时才需要）。

### 实现时的校验规则（来自 manager-api 错误码）

- OTA 地址**必须以 `/ota/` 结尾**
- 不能用 `localhost` / `127.0.0.1`（设备在别的机器上）
- 必须以 `http` / `https` 开头
- WebSocket 地址同样不能用 localhost

---

## 六、方案：两阶段推进

### 阶段 1：本地跑通服务（不碰硬件）★ 从这里开始

仓库位置：`E:\elderly_companion\xiaozhi-server`（2026-10-13 起已合并进老人陪伴主项目；小智官方完整仓库含 manager 管理后台/digital-human 等，未合并部分仍在原 `E:\company\xiaozhi-esp32-server`）

**先读这几个文件**：

| 文件 | 用途 |
|---|---|
| `docs/Deployment.md` | 方式一：Docker 只运行 Server（最简） |
| `docs/all-in-one-digital-human-setup.md` | 数字人一体化搭建 |
| `docs/firmware-setting.md` | 固件侧设置（含改 OTA 地址） |
| `xiaozhi-server/docker-compose.yml` | 部署编排文件 |
| `xiaozhi-server/config.yaml` | 服务配置（ASR/LLM/TTS provider） |
| `xiaozhi-server/requirements.txt` | Python 依赖清单 |
| `digital-human/README.md`（未合并，仍在原仓库 `E:\company\xiaozhi-esp32-server\main\digital-human`） | 网页测试客户端用法 |

**Docker 最简启动**：

```bash
cd xiaozhi-server
docker compose up -d
docker logs -f xiaozhi-esp32-server
```

镜像走 `ghcr.nju.edu.cn`（南大镜像，国内可访问），仅支持 x86 架构。

**核心价值**：用 `digital-human/`（未合并，仍在原仓库 `E:\company\xiaozhi-esp32-server\main\digital-human`）的**网页客户端扮演"狗"** —— 界面上直接填 OTA 地址就能测通整条链路（OTA → WebSocket → 语音对话）。
**不用碰硬件，失败了也不会把狗变砖。**

### 阶段 2：让狗指向自己的服务器

两条路，推荐第一条：

1. **DNS 劫持**（不改固件）：路由器加一条 `api.tenclass.net` → PC 的 IP
2. **重编固件**：改 `main/Kconfig.projbuild` 里的 `OTA_URL` default 值
   ```bash
   python ./scripts/build.py espressif/esp-hi
   idf.py flash
   ```
   ⚠️ ESP-Hi 烧录要点：**断开身体只留头部、按住按钮再连电脑**（舵机占用了 USB Type-C）

---

## 七、待确认事项

- [ ] 设备的 OTA 请求是否真发往 `api.tenclass.net`（还是配网时可填服务器地址）
- [ ] 设备首次是否需要**激活码**（开源实现里可配置免激活）
- [ ] 隐藏动作 ID `1 / 3 / 11` 是否存在
- [ ] `USE_AUDIO_DEBUGGER` 是否可用 —— 开了它设备会把原始音频通过 UDP 发到指定主机（默认 `192.168.2.100:8000`），对自建服务极有用

---

## 八、命令速查

```bash
# 探测设备
curl -s http://192.168.31.91/status                      # {"listening":false}
curl -s http://192.168.31.91/ | head -40                 # 控制台 HTML

# 控制
curl -X POST http://192.168.31.91/control -H "Content-Type: application/json" -d '{"action":"7"}'
curl -X POST http://192.168.31.91/control -H "Content-Type: application/json" -d '{"move":"F"}'

# 抓控制页面的 JS（805 行，含全部动作表）
curl -s http://192.168.31.91/main.js
```

### 环境备忘（重要）

**GitHub 直连不通（443 超时），但本机有代理可用**：

```bash
# 代理在 127.0.0.1:7890，拉代码时显式指定即可
git -c http.proxy=http://127.0.0.1:7890 -c https.proxy=http://127.0.0.1:7890 clone <github-url>

# curl 同理
curl -x http://127.0.0.1:7890 <url>
```

当前桌面仓库即通过代理拉取的**官方版本**（1617 文件）。
（早先无代理时曾从 `gitee.com/mayjean/xiaozhi-esp32-server` 镜像克隆过一份，已弃用。）

**git bash 中文文件名注意**：`cp` / `find` 对中文路径处理异常，涉及中文文件名时改用 Read/Write 工具或 PowerShell。

---

## 九、参考资料

- 固件：[78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32)（MIT，约 29.9k star）
  - ESP-Hi 板卡：`main/boards/espressif/esp-hi/`
  - 关键配置：`main/Kconfig.projbuild`（`OTA_URL`、`WAKE_WORD_TYPE`）
- 后端：[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)（约 9.1k star）
  - OTA 实现：`xiaozhi-server/core/api/ota_handler.py`
  - 网页客户端：`main/digital-human/`
  - 部署文档：`docs/Deployment.md`、`docs/firmware-build.md`
- 硬件开源：[立创开源 ESP-Hi](https://oshwhub.com/esp-college/esp-hi)

### 行业延迟基线（可作谈资）

VAD 检测 200–400ms → ASR 首字 ~500ms → LLM 首 token 300–600ms

### 行业架构共识

- **端云混合**：端侧管唤醒/VAD/指令，云端管 ASR/LLM/TTS
- **离线人格优先**：断网不能变砖，要优雅降级
- **端侧保留安全裁决权**：云端建议动作，端侧决定是否安全执行
- **每增加 ~300ms 延迟就可感知**

# vision_control —— 电脑视觉识别 → 机器狗指令（PC 端）

用电脑摄像头识别人体姿势和手部手势，直接驱动 ESP-Hi 机器狗（HTTP `/control`）。

```
摄像头 → 检测后端(MediaPipe / YOLO11-Pose) → 动作规则 → 指令闸门 → 下发(dry-run / HTTP / WebSocket)
```

## 快速开始

```sh
# 1. 仅识别测试（打印报文，不驱狗）
python vision_dog.py

# 2. 接真狗（ESP-Hi 机器狗，HTTP /control）
python vision_dog.py --http http://10.1.56.231

# 3. 接 eda-robot-pro 板（WebSocket MCP，需固件先改）
python vision_dog.py --ws ws://192.168.1.30:8080/ws
```

**下发器优先级**：`--http` > `--ws` > dry-run（三选一）

---

## 两种识别后端（用 `--backend` 切换）

| | `--backend mediapipe`（默认） | `--backend yolo` |
|---|---|---|
| 模型 | pose_landmarker_lite + hand_landmarker | yolo11n-pose.pt（6MB） |
| 关键点 | 33 点（含手指 21 点 × 2 手） | 17 点 COCO（无手部） |
| 实测帧率 | ~20 fps | ~18 fps（54ms/帧，CPU） |
| 手部手势 | 支持 | 默认关闭，加 `--with-hands` 用 MediaPipe 补上 |
| 适合 | 想要手势指令、画面里人多 | 想要一套通用的检测框架、后续好接自训练模型 |

两条路的上层**完全共用**——`detector_yolo.py` 把 COCO 17 点映射成 MediaPipe 的 33 点布局
（左右不交换，两套标注都是"人自己的左右"），规则代码一行没改。

```sh
python vision_dog.py --backend yolo                 # 纯 YOLO：姿势指令可用，手势关闭
python vision_dog.py --backend yolo --with-hands    # YOLO 出姿势 + MediaPipe 出手势
python vision_dog.py --backend yolo --vis-threshold 0.35   # YOLO 关键点置信度天然的偏低
```

> YOLO 的关键点置信度比 MediaPipe 的 visibility 低不少（手腕常在 0.5~0.7），
> 所以 YOLO 后端的默认阈值是 0.4 而不是 0.6，两套默认值分开管理（见 `DEFAULT_VIS`）。

**关于"用 YOLO 直接识别动作"**：YOLO-Pose 本身是**检测器**，输出的是关键点，不是动作标签。
工程上有两条路：

1. **YOLO-Pose（预训练）+ 规则**（本目录已实现）：零训练、当天可用，动作稳定也可控。
2. **训练动作分类模型**：把"每个动作"当成一个类别（如 `raise_both_hands`），需要采集几百张
   图并标注，好处是识别端只剩一次推理。适合第 1 条调不动、或要识别复杂动作串时再上。

先用 1 把 demo 跑通，需要再升级到 2，训练脚本可直接用 ultralytics 的 `yolo pose train` 或
分类模型 `yolo classify train`，不换框架。


## 目录结构

| 文件 | 职责 |
|---|---|
| `action_rules.py` | 识别规则（纯逻辑，不依赖 mediapipe，可离线自测） |
| `command_gate.py` | 指令闸门：防抖 + 边沿触发 + 冷却 |
| `detector.py` | MediaPipe Tasks 封装，模型首次运行自动下载 |
| `detector_yolo.py` | YOLO11-Pose 封装 + COCO 17 点→MediaPipe 33 点映射 |
| `emitter.py` | 下发层：dry-run 打印 / HTTP 驱动 ESP-Hi / WebSocket 驱动 eda-robot-pro |
| `vision_dog.py` | 主程序（摄像头 + HUD） |
| `selftest.py` | 离线自测，不需要摄像头 |
| `models/` | MediaPipe `.task` + YOLO `.pt` 模型 |

## 手势 → 狗动作对照（方案 C：映射到 ESP-Hi 预设动作）

| 手势 | 识别 | ESP-Hi `/control` 报文 |
|---|---|---|
| 双手高举过头 | 前进 | `{"move":"F"}`（1.5s 后自动停止） |
| 只举左手 | 左转 | `{"move":"L"}`（1.5s 后自动停止） |
| 只举右手 | 右转 | `{"move":"R"}`（1.5s 后自动停止） |
| 双臂平举成 T 字 | 停止 | `{"move":"S"}` |
| 双手抱头 / 下蹲 | 鞠躬 | `{"action":"2"}` |
| 张开手掌 | 握手 | `{"action":"7"}` |
| 竖大拇指 | 伸懒腰 | `{"action":"9"}` |
| 剪刀手 | 摇摆 | `{"action":"4"}` |

> ESP-Hi 无"坐下/站立"动作，故把这三个姿势手势就近映射到预设动作。
> 映射表在 `emitter.py` 的 `HttpEmitter.ACTION_MAP`，对齐后端 `robot_action.py` 的 `ACTION_MAP`。

## 环境准备

Python 3.9+（本机用 3.13 验证过，mediapipe 1.0.1 + ultralytics 8.4.166）。

**本机已经装好一个 conda 环境，直接用即可：**

```sh
conda activate vision            # 环境位于 D:\study_files\conda\envs\vision
cd vision-control
python selftest.py
python vision_dog.py
```

不想激活也可以直接用绝对路径调用（推荐，省掉激活的坑）：

```sh
D:\study_files\conda\envs\vision\python.exe vision-control\vision_dog.py
```

**如果你要在别的机器上从零装：**

```sh
python -m venv .venv-vision
.venv-vision\Scripts\activate
pip install mediapipe Pillow                 # 先装 mediapipe，它会带 opencv-contrib-python
pip install --no-deps ultralytics             # 关键：跳过 opencv-python，避免和 contrib 冲突
pip install torch torchvision ultralytics-thop ultralytics-platform
```

> **必须按这个顺序装。** mediapipe 依赖 `opencv-contrib-python`、ultralytics 依赖
> `opencv-python`，两个包都会往 `site-packages\cv2\` 写文件，直接一起装会互相覆盖，
> 表现为 `cv2` 导入报错或功能缺失。用 `--no-deps` 装 ultralytics 后它照样能用
> （`cv2` 由 contrib 包提供，是超集），只是 `pip list` 会提示 `opencv-python` 未安装，可忽略。

### 装包时的两个坑（本机实测）

1. **`WinError 5 拒绝访问`**：pip 在写"目录可写性探测文件"时裸调 `os.unlink`，碰上杀软
   瞬时锁文件就会整个安装失败。**直接重试即可**，一般第二次就过。
2. **环境里注入了删除保护插件**（`sitecustomize.py`，通过 `PYTHONPATH` 注入），它会拦 pip
   的临时文件删除。给 pip 命令清空 `PYTHONPATH` 即可绕过，仅对该条命令生效：
   ```sh
   PYTHONPATH= D:\study_files\conda\envs\vision\python.exe -m pip install <包名>
   ```

### 为什么环境不能"剪切粘贴"到别处

venv / conda env 的路径是**写死在文件里**的：`pyvenv.cfg` 记录基础解释器位置，
`Scripts\activate` 内嵌 `VIRTUAL_ENV`，`Scripts\*.exe` 启动器内嵌 python 路径。
搬走之后 `pip.exe` 会去找旧路径。要换位置只能**重建**，不能搬。

## 快速开始

```sh
cd tools/vision_control

python selftest.py                 # 先跑自测，29 项全过再上摄像头
python vision_dog.py               # 默认摄像头，dry-run，画面上按 q 退出
python vision_dog.py --camera 1    # 换摄像头
python vision_dog.py --list-actions
```

## 触发姿势对照表

| 姿势 / 手势 | 指令 | 固件工具 |
|---|---|---|
| 双手向两侧上方张开举过头 | 前进 | `self.dog.walk(steps=4, speed=1000, direction=1)` |
| 只举左手（另一只手没举起来即可） | 左转 | `self.dog.turn(steps=4, speed=2000, direction=1)` |
| 只举右手 | 右转 | `self.dog.turn(steps=4, speed=2000, direction=-1)` |
| 双臂平举成 T 字 | 停止 | `self.dog.stop()` |
| 双手抱头（或下蹲） | 坐下 | `self.dog.sit(speed=1500)` |
| 张开手掌 | 站立 | `self.dog.stand(speed=1500)` |
| 竖大拇指 | 伸展 | `self.dog.stretch(speed=2000)` |
| 剪刀手 | 摇摆 | `self.dog.shake(speed=1000)` |

判定优先级：**全身姿势 > 手部手势**。举手类动作用姿势判定；手部手势请在手臂自然下垂时比出。

## 为什么需要"指令闸门"（比识别本身更重要）

1. **防抖**：逐帧判定必然抖动，姿势需连续保持 `--hold-frames`（默认 8 帧 ≈ 0.3s）才算数。
2. **边沿触发**：机器狗的动作是阻塞式的（`walk` 默认 4 步、每步约 1 秒），指令必须
   "做一次 → 放下手回中立位 → 再做一次"才会发下一条，否则全堆进设备队列，看着像死机。
3. **冷却**：两条指令之间至少隔 `--cooldown` 秒（默认 2.0）。

可调参数：

```sh
python vision_dog.py --hold-frames 12 --cooldown 3.0   # 更保守，误触发更少
python vision_dog.py --hold-frames 5  --cooldown 1.0   # 更灵敏
```

## 接到真狗（等固件改好后）

机器狗板子（`eda-robot-pro`）目前只有云端 MCP 通道，PC 连不上。需要把
`main/boards/otto-robot/websocket_control_server.{h,cc}` 搬过去（otto-robot / electron-bot
已经在用，端口 8080，路径 `/ws`，收到 JSON 直接喂 `McpServer::ParseMessage`），并在
`main/boards/lceda-course-examples/eda-robot-pro/config.json` 的 `sdkconfig_append` 加上
`CONFIG_HTTPD_WS_SUPPORT=y`。

固件就绪后，只需加一个参数：

```sh
python vision_dog.py --ws ws://<机器狗的IP>:8080/ws
```

报文格式已按 `main/mcp_server.cc` 对齐：`jsonrpc: 2.0`、`method: tools/call`、
`params.name` / `params.arguments`，**`id` 必须是数字**（固件用 `cJSON_IsNumber` 校验），
`arguments` 的键名与 `eda_dog_controller.cc` 里 `Property(...)` 完全一致。

## 调试建议

- **误触发多** → 加大 `--hold-frames` 和 `--cooldown`；确认手别一直搭在桌沿（手腕要在画面内）
- **没反应** → 确认肩部完整入镜；举手要举过鼻子高度；单手举起时另一只手不要也举着
- **卡顿** → 关掉其他占用摄像头的程序；`detector.py` 里用的是 lite 模型，够快
- 笔记本摄像头只拍得到上半身也能用：单手举、抱头、手势都不依赖下半身；只有"下蹲"需要腿部入镜

## 已知限制

- 单目摄像头没有深度，"双手前推/后拉"这种前后动作判不准，所以词汇表里没有后退
- 下蹲检测依赖膝盖角度，腿不在画面内时不会触发（可以改用"双手抱头"）
- 强逆光、侧脸、距离太远都会降低识别率
- 手部手势刻意只做"手指明显伸直"的三种，不做握拳——放松的手太像握拳，会疯狂误触发

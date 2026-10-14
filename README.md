# 老人情感陪伴 AI Demo（含 ESP-Hi 机器狗控制）

> 2026-10-13：机器狗相关代码已从 `xiaozhi-esp32-server` 合并入库（`xiaozhi-server/` + `vision-control/` + `web-control/`），详见文末「机器狗子系统」。
> 2026-10-13：新增「每日陪伴日报」——每天定时把老人聊天汇总（统计 + AI 摘要）推送家属看板，详见文末同名章节。

第一阶段 Qwen API 版本。**本地不下载任何大模型、不训练、不微调、不需要 GPU**，所有模型能力通过通义千问（DashScope OpenAI 兼容端点）远程 API 获得。

## 当前进度：第一阶段完成 + 架构升级（语义检索 + Agent 化 + 语音）

```
用户输入（文字 / 语音）
   ↓
【ASR 语音识别】录音 → DashScope 转写 → 文字（按住说话，零本地模型）
   ↓
【LangGraph Agent 编排】START → analyze → context → generate → END
   ├─ analyze 工具：情绪/意图/场景/需求/风险 → 结构化 JSON（失败自动降级）
   ├─ context 工具：画像 + 短期记忆 + 长期记忆（语义检索）+ 策略决策 + 内容推荐
   └─ generate 工具：画像+记忆+情境+策略+推荐 注入 System Prompt，生成回复
   ↓
【TTS 语音合成】回复文字 → 音频 URL → 网页播放（每条回复可听）
   ↓
落库（对话 + emotion_records 情绪历史）+ 后台记忆提取
```

- **7 轮基础开发**已完成（最小可运行 → 画像/短期记忆 → 长期记忆 → 情境分析 → 陪伴策略 → 音乐/故事/游戏 → Web UI/测试回归）
- **语义检索升级**：长期记忆从字符 bigram 改为 `text-embedding-v3` 向量余弦检索，SQLite 存向量，零向量数据库依赖
- **Agent 化**：LangGraph StateGraph + 三个 `@tool` 工具编排，替代线性 pipeline
- **决策可视化**：每条回复下方展示「情绪 → 意图/场景 → 动作(理由) → 推荐 → 记忆」完整因果链
- **语音**：TTS（qwen-audio-3.0-tts-flash）+ ASR（paraformer-v2），全部远程 API，零本地模型
- **性能优化**：端到端 11.3s → 4.5s（快 2.5 倍），详见下方「性能优化」
- 47 个测试全绿

## 性能优化

实测端到端 `/chat` 从 **11.3 秒降到 4.5 秒**，四项改动：

| 改动 | 效果 |
|---|---|
| 情境分析改用快模型 `qwen-turbo` | 3.1s → 0.8s（结构化 JSON 任务不需要主模型） |
| 短期记忆窗口 20 轮 → 6 轮 | 注入从 4921 字降到约 1500 字，**收益最大**——长 prompt 让预填充慢，且模型倾向写长文 |
| 长期记忆检索合并为一次批量 embedding | 3.6s → 0.3s（原为两次独立调用） |
| 回复长度硬上限 + prompt 约束 60 字 | 生成 4.6s → 3.4s，且老人本就看不了长篇 |

## 安装

```bash
cd elderly_companion
pip install -r requirements.txt
```

> 依赖中故意不含 torch / transformers 等任何模型库。

## 配置

复制 `.env.example` 为 `.env`，填写：

```env
QWEN_API_KEY=你的API_KEY
QWEN_MODEL=qwen-plus
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_TIMEOUT=60
```

- `QWEN_API_KEY`：在阿里云百炼控制台（https://bailian.console.aliyun.com/）创建
- `QWEN_MODEL`：默认 qwen-plus，可按需改 qwen-turbo / qwen-max
- Key 只放在 `.env` 中，`.gitignore` 已排除，切勿提交

### 邮箱验证码登录

登录页同时保留“密码登录”和“邮箱验证码”两种方式。新用户可以在注册时验证并绑定邮箱；
已有账号登录后进入“账号”页面绑定或更换邮箱，之后即可使用邮箱验证码登录。

正式环境需在 `.env` 中配置 SMTP：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your-account@example.com
SMTP_PASSWORD=your-smtp-password
SMTP_FROM_EMAIL=your-account@example.com
SMTP_USE_TLS=true
SMTP_USE_SSL=false
EMAIL_CODE_EXPIRE_MINUTES=10
EMAIL_CODE_COOLDOWN_SECONDS=60
EMAIL_CODE_MAX_ATTEMPTS=5
```

本地 `development` 环境未配置 SMTP 时，发送接口会返回 `debug_code`，前端会自动填入该测试验证码；
`production` 环境不会返回明文验证码，且未配置 SMTP 时会拒绝发送。

## 运行

```bash
python run.py
```

打开浏览器访问：**http://127.0.0.1:8000**

输入「今天有点无聊。」，即可收到真正由 Qwen API 生成的陪伴式回复。

## API

### POST /chat

```json
{ "user_id": "elderly_001", "message": "今天一个人在家，感觉有点无聊。" }
```

返回：

```json
{
  "reply": "……",
  "user_id": "elderly_001",
  "name": "王阿姨",
  "emotion": "lonely",
  "emotion_intensity": 0.68,
  "intent": "emotional_sharing",
  "scene": "alone",
  "topic": "孤独",
  "need": "companionship",
  "risk_level": "low",
  "degraded": false,
  "recalled_memories": ["老人的女儿叫小芳"]
}
```

### GET /profile/{user_id}、PUT /profile/{user_id}

读取 / 局部更新老人画像。首次访问自动建档：`elderly_001` 预置为「王阿姨」演示档案（女儿小芳、喜欢邓丽君、纺织厂经历），其他 user_id 得到干净的默认画像。

### GET /emotion/{user_id}

查看情绪历史（emotion_records 表），用于观察情绪趋势。

### GET /memory/{user_id}/state

查看短期记忆：当前主题/情绪/场景/意图 + 最近 10 轮对话。

### GET /memories/{user_id}、DELETE /memories/{user_id}/{memory_id}

查看 / 删除该老人的长期记忆。长期记忆由后台 Qwen 调用自动判断写入（不存寒暄，只存事实，自动去重），因此 /chat 返回后约 2~5 秒新记忆才会入库。

### POST /recommend/music、POST /recommend/story

按 画像 + 当前情绪 + 场景 推荐音乐/故事（本地数据 + 打分，不依赖 Qwen）。

### POST /game/new、POST /game/check

益智游戏：数字记忆 / 简单算术 / 成语接龙。出题与判题为本地规则（成语接龙在 Qwen 可用时用其生成），不依赖 Qwen 也可玩。

### POST /speech/tts、POST /speech/asr

语音合成与识别（远程 API）。TTS 输入 `{"text": "..."}` 返回音频 URL（24h 有效）；ASR 上传音频文件返回识别文本。Web 页面每条 AI 回复带「播放」按钮，输入框旁「🎤」按住说话。

### GET /health

返回服务状态、当前模型名、API Key 是否已配置。

### RAG 知识库（`/api/v1/knowledge/*`）

知识库用于存放护理手册、常见问题、家庭约定等外部资料。文档导入后会自动按段落/句子分块，
尝试调用 `text-embedding-v3` 生成向量并存入数据库；没有 API Key 或 embedding 暂时不可用时，
仍可用中文词面匹配检索。聊天流程会自动检索全局资料和当前老人专属资料，并把相关来源返回在
`knowledge_sources` 字段中。

- `POST /api/v1/knowledge/documents`：家属账号导入文本知识；`scope` 可选 `global` 或 `elderly`
- `GET /api/v1/knowledge/documents`：查看当前家属创建的文档及分块数量
- `DELETE /api/v1/knowledge/documents/{id}`：删除自己创建的文档及其分块
- `POST /api/v1/knowledge/search`：手动测试检索，聊天时无需单独调用

导入示例：

```json
{
  "title": "跌倒后的照护流程",
  "source": "家庭护理手册",
  "scope": "global",
  "content": "老人跌倒后先保持平静，不要急着扶起，应观察是否受伤并联系家人。"
}
```

`scope=elderly` 时还需要传 `elderly_user_id`，并且操作者必须已经绑定该老人。
家属创建的 `global` 文档只会共享给该家属绑定的老人，不会影响其他家庭；只有系统直接导入、
`created_by` 为空的公共资料才会对所有老人可见。

项目内置的基础资料位于 `data/knowledge_base.json`。首次部署后执行：

```bash
python scripts/seed_knowledge.py
```

脚本可重复运行，相同内容不会重复写入，并会自动为缺少向量的分块补建 Embedding。
没有可用的 Embedding 服务时，可使用 `python scripts/seed_knowledge.py --no-embed` 离线导入，
系统会自动使用关键词检索兜底。

## 部署上线（老人端 / 家属端 多客户端）

后端为**无状态 JWT 鉴权**，天然支持任意多个客户端：老人用一台设备、家属用另一台设备，
访问同一个前端地址、各自登录即可实时双向互动（情绪看板、留言/牵挂等）。

### 方式一：局域网 / 单机多人测试
1. 启动后端（`python run.py`，:8000）与前端（`cd web_next && npm run start`，:3000）；
2. 让另一台设备（手机/平板）连同一 WiFi，访问 `http://<本机IP>:3000`
   （Windows 查 IP：`ipconfig`；必要时放行防火墙 3000 端口）；
3. 设备 A 登录老人账号、设备 B 登录家属账号，即可同时在线互动。

### 方式二：Docker 一键上线
```bash
cp .env.example .env          # 至少填 QWEN_API_KEY；生产务必改 JWT_SECRET_KEY
docker compose up -d --build  # db(PostgreSQL) + api(:8000) + web(:3000)
```
- 前端容器通过 `BACKEND_URL=http://api:8000` 代理 `/api/v1` 到后端；
- 该地址在**构建期**由 `web_next/Dockerfile` 的构建参数注入（Next rewrites 在构建期固化）。

### 生产建议
- 用 **Nginx 同域反向代理**：`/` → `web:3000`、`/api/` → `api:8000`，前后端同源可省去 CORS；
- 配置 HTTPS（如 Let's Encrypt）；
- 替换强 `JWT_SECRET_KEY`；数据库改用 PostgreSQL（`DATABASE_URL`）；
- 跨域部署时用 `CORS_ORIGINS` 填前端正式域名（逗号分隔多个）。

### 关键环境变量
| 变量 | 说明 |
|---|---|
| `QWEN_API_KEY` | 通义千问 API Key（必填） |
| `DATABASE_URL` | 默认 SQLite；生产用 `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET_KEY` | JWT 签名密钥（生产必须替换） |
| `CORS_ORIGINS` | 允许跨域的前端地址，逗号分隔 |
| `ENVIRONMENT` | development / production |
| `BACKEND_URL`（前端） | 前端 `/api` 代理目标，默认 `http://localhost:8000` |

## 测试

```bash
python -m pytest tests -v -s       # 全部（无 Key 或账户欠费时真实 API 用例自动跳过）
```

## 项目结构

```
elderly_companion/
├── app/                        # 老人陪伴 FastAPI 后端（:8000）
│   ├── main.py / config.py     # 入口 + .env 配置（含小智视觉/机器狗地址）
│   ├── api/v1/                 # auth/chat/dog/emotion/vision/speech/family/knowledge...
│   ├── services/dog_control.py # 机器狗动作控制（HTTP → ESP-Hi 固件 /control）
│   ├── agent/ memory/ emotion/ companion/ rag/ scheduler/ scene/ content/
│   └── speech/                 # TTS+ASR（DashScope 远程，零本地模型）
├── web_next/                   # Next.js 前端（:3000），/api/v1 代理到后端
├── xiaozhi-server/             # 小智 ESP32 服务（2026-10 合并自 xiaozhi-esp32-server）
│   ├── app.py                  # WS :8001（设备语音通道）+ HTTP :8003（OTA/视觉）
│   ├── config.yaml             # 基础配置；data/.config.yaml 为运行期覆盖配置（勿入库）
│   ├── plugins_func/functions/robot_action.py  # LLM 控狗工具（与 dog_control.py 协议一致）
│   └── models/snakers4_silero-vad/   # SenseVoiceSmall(897M) 已排除：当前未启用本地 ASR
├── vision-control/             # PC 摄像头手势/姿势识别 → /control（MediaPipe/YOLO）
├── web-control/                # 机器狗网页调试台（:8080，不接真机时调试用）
├── docs/                       # 机器狗整合规划 / 启动指南 / ESP-Hi 探索记录 + 启动_全功能.bat
├── storage/companion.db        # SQLite（运行时自动创建）
├── docker-compose.yml          # db + api + web + xiaozhi 四服务编排
└── run.py
```

### 机器狗子系统（合并内容，2026-10-13）

原 `xiaozhi-esp32-server` 项目的机器狗相关代码已合入本仓库，未合并的部分（小智官方 manager 管理后台 / digital-human 数字人）仍在 `E:\company\xiaozhi-esp32-server`：

| 目录 | 职责 | 启动方式 |
|---|---|---|
| `xiaozhi-server/` | ESP32 设备的语音通道（WS 8001）+ OTA/视觉接口（8003） | `docs\启动_全功能.bat` 或 `python app.py`（需含 funasr 的 Python 环境） |
| `web-control/` | 网页调试台，连 WS 发指令、快捷动作按钮 | `python server.py`（8080） |
| `vision-control/` | 电脑摄像头手势识别 → HTTP `/control` 驱狗 | `python vision_dog.py --http http://10.1.56.231` |

老人陪伴后端与小智服务的协作：`app/api/v1/vision.py` 把老人端照片转发到小智的 MCP Vision 接口（`XIAOZHI_VISION_URL`）做图像理解；`app/services/dog_control.py` 直接驱动机器狗固件。详细整合背景见 `docs/机器狗整合规划.md`。

## 每日陪伴日报（家属推送）

每天 20:30（可配 `DIGEST_HOUR`/`DIGEST_MINUTE`）自动把老人当天与陪伴助手的聊天汇总成一条日报，推进家属看板（`/family` 页「家人和系统消息」）：

- **统计**：聊天轮数、主情绪、情绪分布、话题 Top3、活跃时段
- **AI 摘要**：主模型生成 100 字以内温馨摘要（如"今天心情不错……建议家人抽空视频聊聊"）；LLM 不可用时自动降级为纯统计文本，日报保证送达
- **同日去重**：同一老人同一天只推一次；当天没聊天/未绑定家属则不推
- **实时触达**：生成时经 SSE 通知在线家属，未读显示「新」角标

涉及文件：`app/services/digest_service.py`（统计+摘要）、`app/scheduler/jobs/daily_digest.py`（定时任务）、`app/scheduler/scheduler_manager.py`（注册）、`web_next/src/app/family/page.tsx`（日报卡片）。

> 注意：调度器在生产环境自动运行；开发环境需在 `.env` 设 `SCHEDULER_ENABLED=true` 才会启动（默认关闭，避免本地跑出一堆定时副作用）。

## 异常处理说明

- Key 未配置：/chat 返回 502 并带明确提示，服务启动时日志告警
- 网络错误 / 超时 / 非 200 / 响应结构异常：统一抛 `LLMError`，路由转 502
- 空输入 / 非法 user_id：422/400 拒绝
- 日志只打印模型名与 token 用量，**绝不打印 API Key**

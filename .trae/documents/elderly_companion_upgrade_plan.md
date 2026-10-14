# 老人情感陪伴 AI — 创业产品化升级方案

## Context

当前项目是一个功能完整的 Demo（7 轮迭代 + 架构升级），LangGraph Agent 编排、陪伴策略规则引擎、安全策略、语义记忆检索等核心设计已经很好。但要成为真正的创业产品，存在三大短板：**无认证（任何人可伪造 user_id 查看他人画像）、同步阻塞（ASR 轮询阻塞事件循环 120 秒、LLM 调用阻塞线程）、单文件前端（无移动适配、无 PWA）**。

本方案分三阶段，从"可登录可部署的 MVP"到"主动关怀 + 情绪预警"再到"规模化可观测"，逐步将 Demo 升级为产品。

---

## 现状评估：保留 / 升级 / 替换

### 保留（设计良好，直接迁移）

| 模块 | 文件 | 理由 |
|---|---|---|
| LangGraph Agent | `app/agent/companion_agent.py` | StateGraph + @tool 工具化，已支持依赖注入 |
| 陪伴策略引擎 | `app/companion/companion_policy.py` | 确定性决策 + 可解释 reason，产品可控性核心 |
| 安全策略 | `app/companion/safety.py` | 高危正则 + Qwen 双校验 + 安全话术 |
| Prompt 拼装 | `app/companion/prompts.py` | 结构化分块注入，build_messages 契约稳定 |
| 情境分析器 | `app/emotion/emotion_analyzer.py` | 结构化 JSON + 枚举校验 + 降级 |
| 长期记忆检索 | `app/memory/long_memory.py` | 向量余弦 + 去重，换存储层即可 |
| 记忆提取器 | `app/memory/memory_extractor.py` | 独立判断"是否值得记住" |
| 老人画像 | `app/profile/elderly_profile.py` | Pydantic 模型 + prompt_block() |
| 内容推荐 | `app/content/*.py` | 本地数据 + 规则打分 |
| LLMClient ABC | `app/llm/qwen_client.py` | 抽象接口已就位 |

### 升级（逻辑保留，实现层改造）

| 模块 | 问题 | 方向 |
|---|---|---|
| QwenClient | 同步 httpx.post，每次 /chat 阻塞 3~4s | → AsyncQwenClient (httpx.AsyncClient) |
| SpeechClient | time.sleep 轮询 + async def 调同步 = 阻塞事件循环 | → AsyncSpeechClient + ASR 拆成提交/查询两步 |
| routes.py | 无 auth、无版本前缀、无限流 | → 拆分到 api/v1/ + JWT 依赖 |
| ShortMemory | MAX_TURNS=6 固定，无摘要 | → 加对话摘要压缩层 |
| config.py | 只有 Qwen 配置 | → Pydantic Settings 多环境 |
| db.py | SQLite + 手写 schema | → PostgreSQL + SQLAlchemy + Alembic |
| web/index.html | 单文件，移动端差 | → Next.js + PWA |

### 替换

- `app/main.py` lifespan + StaticFiles → 生产 ASGI（CORS/限流/Router 注册）
- `run.py` → Gunicorn + uvicorn workers 或容器入口
- `requirements.txt` → `pyproject.toml` + uv 锁定版本

---

## 阶段一：MVP 基础（3~4 周）

目标：可登录、可部署、前后端分离。不引入 Redis/Worker。

### 1.1 后端：异步化 + 认证 + PostgreSQL

**新增文件结构**：

```
app/
├── main.py                    # 重写：CORS + 限流 + Router + lifespan
├── config.py                  # 重写：Pydantic Settings 多环境
├── core/
│   ├── security.py            # JWT 签发/校验 + bcrypt 密码哈希
│   ├── dependencies.py        # get_current_user / rate_limiter
│   └── logging.py             # structlog 结构化日志
├── db/
│   ├── base.py                # SQLAlchemy 引擎 + SessionLocal + Base
│   ├── session.py             # get_db 依赖注入
│   └── models.py              # ORM：accounts / elderly_profiles / family_members /
│                              #   conversations / memories / emotion_records /
│                              #   conversation_summaries / refresh_tokens
├── repositories/              # 数据访问层（从 short_memory/long_memory/ProfileStore 迁移）
│   ├── profile_repo.py
│   ├── conversation_repo.py
│   ├── memory_repo.py
│   └── emotion_repo.py
├── schemas/                   # Pydantic 请求/响应模型
│   ├── auth.py / chat.py / profile.py / emotion.py
├── api/v1/
│   ├── router.py              # 聚合子路由
│   ├── auth.py                # /register /login /refresh /me
│   ├── chat.py / profile.py / memory.py / emotion.py
│   ├── content.py / speech.py / health.py
│   └── deps.py                # 路由公共依赖
├── llm/
│   ├── base.py                # LLMClient ABC 抽出
│   └── qwen_client.py         # → AsyncQwenClient
├── agent/companion_agent.py   # 保留，节点改 async + ainvoke
├── companion/                 # 保留（policy/safety/prompts）
├── emotion/...                # 保留
├── memory/                    # repo 换层，逻辑保留，改 async
├── speech/speech_client.py    # → AsyncSpeechClient
└── ...
alembic/ + alembic.ini
pyproject.toml
```

**关键改造**：

1. **AsyncQwenClient**：`httpx.post` → `async with httpx.AsyncClient() as c: await c.post(...)`。Agent 三节点改 `async def`，`graph.ainvoke()` 替代 `graph.invoke()`

2. **JWT 认证**：
   - `create_access_token(sub=user_id)` / `create_refresh_token`
   - 用户类型：`elderly`（老人）/ `family`（家属，可绑定多个老人）
   - 密码用 `passlib[bcrypt]`

3. **PostgreSQL + Alembic + pgvector**：
   - `users` 拆成 `accounts`（登录）+ `elderly_profiles`（画像）
   - 新增 `family_members`（家属-老人绑定）、`refresh_tokens`
   - `memories.embedding` 从 TEXT(JSON) → `VECTOR(1024)`（pgvector，比 JSON 快几十倍）
   - 首个 Alembic migration = 完整建表 + 数据迁移脚本

4. **ASR 拆分**（解决最严重阻塞 bug）：
   - `POST /api/v1/speech/asr/submit` → 上传音频、提交任务、返回 task_id
   - `GET /api/v1/speech/asr/{task_id}` → 前端轮询结果
   - 120 秒等待不再阻塞后端

5. **API 版本前缀**：所有路由挂 `/api/v1`

### 1.2 前端：Next.js + PWA + 老人友好 UI

```
web/                            # 替换 index.html
├── package.json
├── next.config.js              # PWA 插件 + standalone 输出
├── tailwind.config.ts           # 老人友好主题
├── public/manifest.json + icons + sw.js
├── src/
│   ├── app/                    # layout / page(聊天) / login / profile / emotion(趋势) / family
│   ├── components/
│   │   ├── chat/               # MessageList / VoiceRecorder / TTSPlayer
│   │   ├── ui/                 # LargeButton / BigInput (shadcn/ui 定制)
│   │   ├── accessibility/      # FontSizeToggle / HighContrastToggle
│   │   └── charts/            # 情绪趋势 (recharts)
│   ├── lib/api.ts              # fetch + JWT 自动注入 + 刷新
│   └── stores/                 # zustand: auth / settings / chat
```

**老人友好设计**：
- 默认字号 18px，可一键放大到 24px
- 高对比度模式（WCAG AAA）
- 语音优先：大 🎤 按钮、按住说话、松开自动发送
- 每条 AI 回复默认自动 TTS 播放（可关）
- 按钮 ≥ 48px 触摸目标
- PWA：可"添加到主屏幕"

### 1.3 工程化：Docker + 基础 CI

```
├── Dockerfile                  # 后端镜像
├── web/Dockerfile              # 前端镜像
├── docker-compose.yml          # api + web + postgres
├── docker-compose.prod.yml     # 生产覆盖
├── .github/workflows/ci.yml    # lint + test + build
├── pyproject.toml              # 替代 requirements.txt
└── Makefile                    # make dev / test / lint / migrate
```

**阶段一验收**：
- 用户可注册登录（老人 + 家属两角色）
- 老人聊天体验与 demo 一致但 ASR 不再阻塞
- 家属可绑定老人、查看情绪历史
- `docker compose up` 一键启动
- CI 在 PR 上跑通 lint + 单元测试

---

## 阶段二：AI 能力增强（3~4 周）

目标：从"被动应答"升级为"主动关怀 + 深度记忆 + 情绪预警"。

### 2.1 主动关怀（定时 check-in）

```
app/services/proactive/
├── scheduler.py            # APScheduler AsyncIOScheduler
├── checkin_policy.py       # 规则：晨/午/晚/深夜独居/久未对话
├── checkin_generator.py    # Qwen 生成个性化问候（注入画像+近况）
└── notifier.py             # WS 推送 / 阶段三接微信短信
```

**触发规则**（确定性规则，延续 CompanionPolicy 风格）：
- 早安：作息 morning_start 后 30 分钟无对话
- 晚安：evening_start 后 2 小时无对话
- 久未对话：距上次 > 6 小时且时段合适
- 深夜独居告警：23:00~05:00 "一个人/睡不着" + risk 历史偏高 → 推送家属
- 情绪连续低落：连续 3 次 sad/lonely/anxious 且 intensity > 0.6 → 家属告警

**衔接**：问候语走 `companion_agent.run()` 的 generate 节点，复用策略与安全模块。

### 2.2 对话摘要 + 记忆巩固

```
app/memory/
├── conversation_summarizer.py   # Qwen 把 N 轮对话压成摘要
└── memory_consolidator.py       # 定时：同类记忆语义相似 >0.85 合并
```

- 超过 8 轮触发摘要：旧轮次 → `conversation_summaries` 表，窗口保留最近 6 轮 + 摘要
- `build_messages` 注入：`[系统 + 画像 + 长期记忆 + 摘要 + 最近6轮 + 当前消息]`
- 每天凌晨记忆巩固：同类记忆合并，旧记忆标记 `superseded_by`

### 2.3 情绪趋势分析与家属告警

```
app/services/emotion/
├── trend_analyzer.py     # 7/30 日情绪分布、连续负向检测
├── alert_policy.py       # 告警规则引擎（确定性）
└── alert_notifier.py     # 推送家属
```

**新增 API**：
- `GET /api/v1/emotion/{user_id}/trend?days=7` → 每日情绪分布 + 趋势方向
- `GET /api/v1/family/alerts` → 家属查看告警
- `PATCH /api/v1/family/alerts/{id}/ack` → 确认告警

**告警规则**：
- 连续 3 天 avg_intensity > 0.7 且主导情绪 ∈ {sad, lonely, anxious}
- 单次 risk_level == high → 立即告警
- 对话频率骤降：本周 < 上周 30%

### 2.4 个性化推荐反馈闭环

- 新增 `recommendation_feedback` 表（accepted/rejected/skipped）
- ChatResponse.recommendation 返回时带 `recommendation_id`
- 前端回调 `POST /api/v1/recommend/{id}/feedback`
- 打分函数加入"历史接受率"权重

**阶段二验收**：
- 个性化早安/晚安（非固定文案，基于画像+近况）
- 连续低落情绪自动告警家属
- 对话超 6 轮不丢上下文（摘要注入）
- 推荐有反馈学习

---

## 阶段三：规模化（3~4 周）

目标：支撑数百~数千并发，可观测、可灰度、可回滚。

### 3.1 Redis + ARQ 异步任务队列

选型：**ARQ**（非 Celery）。原生 asyncio，与 FastAPI 同栈。

```
app/
├── core/redis.py              # redis.asyncio 连接池
├── worker/
│   ├── tasks.py              # asr_poll / memory_extract / summarize / checkin / alert
│   ├── scheduler.py          # ARQ cron jobs
│   └── main.py               # WorkerSettings
```

**Redis 用途**：缓存（/chat 分析结果 5 分钟）、限流（令牌桶）、任务队列、WS 会话存储、分布式锁

### 3.2 WebSocket 实时

- `WS /api/v1/ws` → 主动关怀推送、家属告警、ASR 完成通知
- `app/core/ws_manager.py` → 连接池 + 心跳 + Redis pubsub 多实例广播

### 3.3 可观测性

```
app/core/metrics.py        # prometheus_fastapi_instrumentator
ops/grafana/dashboards/    # Grafana JSON
```

- 指标：http_request_duration / qwen_api_duration / llm_tokens / ws_connections / arq_queue_size
- 告警：/chat p95 > 8s、Qwen 错误率 > 5%、ASR 队列 > 50

### 3.4 CI/CD + 测试

```
.github/workflows/
├── ci.yml        # ruff + mypy + unit test + 覆盖率 80%
├── build.yml     # docker 镜像构建推送
└── deploy.yml    # 滚动更新 + alembic upgrade
tests/
├── unit/         # 迁移现有 47 用例 + 补 trend/policy/summarizer
├── integration/  # TestClient + testcontainers (真实 PG)
├── e2e/          # Playwright: 登录→聊天→情绪→告警
└── load/         # locust: 100 并发 /chat
```

**阶段三验收**：
- 100 并发 /chat p95 < 6s
- Grafana 全链路指标
- 任一组件挂掉系统仍可降级服务（复用现有 degraded 机制）

---

## 必须立即修复的高危问题（阶段一第一周）

1. **ASR 阻塞事件循环**（`app/speech/speech_client.py:141-167`）：`time.sleep` 轮询 + `async def` 调同步函数 → 阻塞所有请求。必须改 `asyncio.sleep` + 拆成提交/查询两步。
2. **QwenClient.chat 同步阻塞**（`app/llm/qwen_client.py:68`）：每次 /chat 阻塞 3~4s，并发 = 线程池大小。改 async 后并发 = 连接池上限。
3. **无认证 user_id 可伪造**（`app/api/routes.py:30`）：任何人可填 `elderly_001` 查看画像和记忆。第一周必须上 JWT。

---

## 新依赖清单

### 阶段一
```
python-jose[cryptography]   # JWT
passlib[bcrypt]             # 密码哈希
sqlalchemy[asyncio]>=2.0    # ORM
asyncpg                      # PostgreSQL async 驱动
alembic                      # 迁移
pgvector                     # 向量列
pydantic-settings            # 配置
structlog                    # 结构化日志
slowapi                      # 限流
pytest-asyncio               # 测试
testcontainers[postgresql]   # 集成测试
```

### 阶段二
```
apscheduler>=4.0            # 异步定时
```

### 阶段三
```
redis[hiredis]>=5.0         # Redis
arq                          # 任务队列
prometheus-fastapi-instrumentator
locust / playwright          # 压测/E2E
```

前端：`next, react, tailwindcss, shadcn/ui, next-pwa, zustand, recharts, @tanstack/react-query`

---

## 迁移策略

### 数据迁移
1. 一次性脚本 `scripts/migrate_sqlite_to_pg.py`：读旧 SQLite → 拆表 → 写 PostgreSQL
2. Alembic 首个 revision = 完整建表
3. 迁移脚本在 Alembic 之后跑一次

### 代码迁移顺序（阶段一内部）
1. 建 `db/` + `repositories/` + `schemas/`（纯新增，不破坏现有）
2. `QwenClient` → `AsyncQwenClient`（影响 agent/emotion/memory/speech 全链路加 async/await）
3. `SpeechClient` → `AsyncSpeechClient` + 拆 ASR 端点
4. 拆 `routes.py` → `api/v1/` 各文件 + 加 auth
5. 删旧 `routes.py` / `db.py`
6. 前端独立开发，旧 `index.html` 保留到阶段一末删

### 保留契约（迁移期间不变）
- `ChatResponse` 字段集合 — 阶段一只加 `recommendation_id`，不改既有字段
- `build_messages(ctx, user_message)` 签名
- `CompanionPolicy.decide(analysis) -> PolicyDecision`
- `assess_safety(message, qwen_risk, qwen_intent) -> (risk, directive)`
- `AnalysisResult` 字段集合

---

## 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 任务队列 | ARQ 非 Celery | 原生 asyncio，与 FastAPI 同栈 |
| ORM | SQLAlchemy 2.0 async | 生态成熟 + Alembic 配套 |
| 向量存储 | pgvector 非独立库 | 数据量级够用，避免多组件运维 |
| 前端 | Next.js 非 Vite | PWA/SSR/路由一体化 |
| UI 库 | shadcn/ui 非 Antd | 可深度定制老人友好样式 |
| 认证 | JWT 非 Session | 前后端分离 + PWA 无状态更合适 |
| 限流 | slowapi→Redis 令牌桶 | 阶段一单实例→阶段三多实例 |

---

## 验证方式

### 阶段一
```bash
# 启动全栈
docker compose up -d
# 跑迁移
alembic upgrade head
# 运行测试
pytest tests/unit -v
# 手动验证
# 1. 注册老人 + 家属账号
# 2. 老人登录 → 聊天 → ASR 语音输入
# 3. 家属登录 → 绑定老人 → 查看情绪历史
# 4. curl /api/v1/health 返回 ok
```

### 阶段二
```bash
# 验证主动关怀
python -c "from app.services.proactive.scheduler import trigger_checkin; trigger_checkin('elderly_001')"
# 验证摘要
# 对话 10 轮后检查 conversation_summaries 表
# 验证告警
# 连续 3 次低落情绪后检查 family alerts API
```

### 阶段三
```bash
# 压测
locust -f tests/load/locustfile.py --users 100 --spawn-rate 5
# 指标
curl /metrics | grep http_request_duration
# 降级测试：停掉 Redis → /chat 应继续工作（缓存降级）
```

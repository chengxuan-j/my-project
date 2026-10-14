# 五项新功能实现计划

## Context

当前老人情感陪伴项目已完成 MVP 基础（JWT 认证、异步全链路、角色分流界面）。用户要求新增 5 项增强功能：主动关怀调度、对话摘要压缩、每日记忆整合、情绪趋势告警、推荐反馈闭环。

---

## 实现顺序

按依赖关系分 6 个阶段串行推进：

### 阶段 1：基础设施（新表 + 新模型 + 依赖）

**新建/修改文件：**
- `requirements.txt` / `pyproject.toml` — 添加 `apscheduler>=3.10`
- `app/db/models.py` — 新增 `FamilyAlert`、`RecommendationFeedback` ORM 模型
- `app/db/legacy.py` — `_SCHEMA` 中补建 `family_alerts`、`recommendation_feedback` 同步表
- `app/schemas/__init__.py` — 新增 `AlertResponse`、`EmotionTrendDay`、`RecommendationFeedbackRequest`；`ChatResponse` 增加 `recommendation_id`
- `app/repositories/profile_repo.py` — `FamilyRepo` 新增 `list_family(elderly_user_id)` 反向查询

### 阶段 2：推荐反馈闭环（功能 5，最独立）

**新建：**
- `app/repositories/feedback_repo.py` — `FeedbackRepo`：add / get_acceptance_rate / get_liked_titles / get_disliked_titles
- `app/api/v1/feedback.py` — `POST /feedback/recommendation`

**修改：**
- `app/content/music.py` — `recommend()` / `pick_for_chat()` 接受 `liked_titles` / `disliked_titles` 参数，不喜欢的降权 2.0
- `app/content/stories.py` — `recommend()` 同上
- `app/memory/memory_manager.py` — `build_context()` 中推荐前查询反馈统计
- `app/api/v1/chat.py` — `ChatResponse` 有推荐时返回 `recommendation_id`
- `app/api/v1/router.py` — 注册 feedback 路由

### 阶段 3：对话摘要压缩（功能 2）

**新建：**
- `app/memory/conversation_summarizer.py` — `ConversationSummarizer`：调用 Qwen 生成对话摘要 / 合并记忆文本

**修改：**
- `app/memory/short_memory.py` —
  - `recent_messages()` 支持读取 `role="summary"` 记录，返回 `[summary] + 最近 6 轮`
  - 新增 `should_compress(user_id)` — 非 summary 行数 > 16 条时返回 True
  - 新增 `compress_old_turns(user_id, summary, keep=6)` — 事务内删除旧行 + 插入 summary
  - 新增 `get_old_turns(user_id, keep=6)` — 获取待压缩的旧对话
- `app/api/v1/chat.py` — `save_turn()` 后检查压缩条件，满足则 `background.add_task(_compress_conversation)`

### 阶段 4：APScheduler 主动问候（功能 1）

**新建：**
- `app/scheduler/__init__.py`
- `app/scheduler/scheduler_manager.py` — 创建 `AsyncIOScheduler`，注册所有 job，提供 `start_scheduler()` / `stop_scheduler()`
- `app/scheduler/jobs/__init__.py`
- `app/scheduler/jobs/proactive_checkin.py` —
  - `morning_greeting_job()` — 每天 8:00，为近 7 天活跃老人发早安
  - `evening_greeting_job()` — 每天 19:00，发晚安
  - `silence_detection_job()` — 每 30 分钟检查，白天超 4 小时无对话则问候
  - `late_night_alert_job()` — 23:30，独居老人仍在活跃则提醒休息
  - 核心函数 `send_proactive_message(user_id, checkin_type)` 调用 `run_agent()` 复用完整生成链路

**修改：**
- `app/main.py` — `lifespan()` 中 `yield` 前 `start_scheduler()`，`yield` 后 `stop_scheduler()`
- 开发环境通过 `settings.environment` 控制是否启用调度器（避免 reload 重复启动）

### 阶段 5：情绪趋势告警（功能 4）

**新建：**
- `app/repositories/alert_repo.py` — `AlertRepo`：create / list_by_elderly / acknowledge / list_for_families
- `app/scheduler/jobs/emotion_alert.py` — `emotion_alert_check_job()`：查最近 3 天 emotion_records，连续 3 天负面情绪(intensity>0.6)则创建告警，24h 内去重

**修改：**
- `app/api/v1/emotion.py` — 新增 `GET /emotion/{user_id}/trend`（按天聚合情绪摘要，家属权限 + 绑定校验）
- `app/api/v1/family.py` — 新增 `GET /family/alerts`（查看绑定老人的告警）、`POST /family/alerts/{id}/ack`（确认告警）

### 阶段 6：每日记忆整合（功能 3）

**新建：**
- `app/scheduler/jobs/memory_consolidation.py` — `memory_consolidation_job()`：
  - 遍历所有有记忆的用户
  - 两两计算 embedding 余弦相似度，> 0.85 的用 Union-Find 聚类
  - 每组取 importance 最高的为主记忆，调用 Qwen 合并文本，更新主记忆 + 删除其余

**修改：**
- `app/scheduler/scheduler_manager.py` — 注册午夜 00:00 cron 任务

---

## 新建文件清单（10 个）

| 文件 | 职责 |
|------|------|
| `app/scheduler/__init__.py` | 调度器包 |
| `app/scheduler/scheduler_manager.py` | APScheduler 生命周期 |
| `app/scheduler/jobs/__init__.py` | jobs 子包 |
| `app/scheduler/jobs/proactive_checkin.py` | 主动问候 4 种 job |
| `app/scheduler/jobs/memory_consolidation.py` | 每日记忆整合 |
| `app/scheduler/jobs/emotion_alert.py` | 情绪趋势告警 |
| `app/memory/conversation_summarizer.py` | Qwen 摘要生成 |
| `app/repositories/alert_repo.py` | 告警数据访问 |
| `app/repositories/feedback_repo.py` | 反馈数据访问 |
| `app/api/v1/feedback.py` | 反馈 API |

## 修改文件清单（14 个）

| 文件 | 修改内容 |
|------|---------|
| `requirements.txt` | +apscheduler |
| `pyproject.toml` | +apscheduler |
| `app/db/models.py` | +FamilyAlert, +RecommendationFeedback |
| `app/db/legacy.py` | +family_alerts, +recommendation_feedback 表 |
| `app/schemas/__init__.py` | +AlertResponse, +EmotionTrendDay, +RecommendationFeedbackRequest, ChatResponse+recommendation_id |
| `app/repositories/profile_repo.py` | FamilyRepo+list_family() |
| `app/memory/short_memory.py` | recent_messages 支持 summary, +压缩方法 |
| `app/memory/memory_manager.py` | 压缩触发 + 推荐集成反馈 |
| `app/content/music.py` | 推荐打分接受反馈参数 |
| `app/content/stories.py` | 同上 |
| `app/api/v1/chat.py` | +压缩后台任务, +recommendation_id |
| `app/api/v1/emotion.py` | +trend 端点 |
| `app/api/v1/family.py` | +alerts 端点 |
| `app/api/v1/router.py` | +feedback 路由 |
| `app/main.py` | lifespan 集成 APScheduler |

---

## 关键技术决策

1. **调度器**：APScheduler `AsyncIOScheduler`，运行在 FastAPI 事件循环内，无需额外进程
2. **同步/异步边界**：调度器 job 中 DB 操作用同步 `get_conn()`（与 ShortMemory/LongMemoryStore 一致），调用 `run_agent()` 时用 async
3. **对话压缩存储**：复用 `conversations` 表，`role="summary"` 记录摘要，事务内原子操作
4. **记忆整合算法**：Union-Find 聚类（阈值 0.85），每组一次 Qwen 合并调用
5. **告警去重**：创建前检查 24h 内同类型告警是否存在
6. **开发环境调度器**：通过 `settings.environment` 控制，开发模式默认不启动（避免 reload 问题）

## 验证方式

1. 启动后端 `python run.py`，确认无报错
2. 运行 `pytest` 确认现有测试不被破坏
3. 推荐反馈：POST /feedback/recommendation → 再次聊天验证推荐排序变化
4. 对话压缩：发送 >8 轮对话后检查 conversations 表出现 summary 记录
5. 主动问候：手动调用 job 函数验证生成效果
6. 情绪告警：插入 3 天负面 emotion_records → 调用 check job → 验证 family_alerts 表
7. 记忆整合：插入相似记忆 → 调用 consolidation job → 验证合并结果

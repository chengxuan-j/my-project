# 设计系统与迁移指南

> 本项目使用**语义令牌 + 可切换主题 + UI 原语组件**的样式体系。三套主题（粉彩 pastel / 雾白 soft / 陶土 warm）
> 来源于 [StyleKit](https://github.com/AnxForever/stylekit)（MIT）的风格规格，映射到同一套语义 CSS 变量。

## 页面结构规范（新）

每个页面统一使用以下原语组装，不再手写裸 `div` 堆叠：

| 原语 | 位置 | 用途 |
|---|---|---|
| `PageHeader` | `components/ui/PageHeader.tsx` | 页面头部：eyebrow 眉题 / title / description / actions / icon |
| `SectionCard` | `components/ui/SectionCard.tsx` | 内容区块：title / icon / meta / actions + 统一卡片头 |
| `StatCard` | `components/ui/StatCard.tsx` | 指标卡：label / value / unit / hint / icon / tone |
| `Badge` | `components/ui/Badge.tsx` | 状态胶囊：tone = primary/success/danger/warning/accent/neutral |
| `EmptyState` | `components/ui/EmptyState.tsx` | 空状态：icon / title / description / action |

页面骨架模板：

```tsx
<div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
  <PageHeader
    eyebrow="分区名"
    title="页面标题"
    description="一句话说明"
    icon={<Icon className="h-7 w-7 text-primary" />}
    actions={<LargeButton>主操作</LargeButton>}
  />
  <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
    <StatCard label="指标" value={12} unit="条" />
  </div>
  <div className="grid lg:grid-cols-[360px_1fr] gap-5 items-start">
    <SectionCard title="侧栏" icon={<Icon />}>…</SectionCard>
    <SectionCard title="主区" icon={<Icon />}>…</SectionCard>
  </div>
</div>
```

桌面端页面一律用 `max-w-5xl`/`max-w-6xl` + 双栏栅格；移动端单列。

## 主题机制

- 主题以 `html.theme-pastel / theme-soft / theme-warm` class 切换（`SettingsProvider` 写入，zustand persist 存储，layout 里内联脚本防首帧闪烁）。
- 页面代码**永远只用语义类**，不允许出现任何具体颜色（warm-*、amber-50、sky-500、#hex 等）。
- 例外：`LetterArrivalModal` 信笺仪式界面属于刻意保留的纸色艺术方向（固定暖纸色）。
- 通话页 `/call` 跟随主题：使用 `call-screen / call-ink / call-muted / call-faint / call-glass / call-accent` 等专用令牌类（变量定义见 globals.css 的 `--call-*`），三套主题各有专属通话底色与强调色。
- 令牌定义在 `src/app/globals.css` 的 `:root` 与 `html.theme-*` 中；Tailwind 映射在 `tailwind.config.ts`。

## 可用语义类

| 用途 | 类 |
|---|---|
| 页面底 | `bg-canvas` |
| 卡片 / 浮层 | `bg-card` `bg-card-soft` |
| 标题正文 / 次级 / 占位 | `text-ink` `text-muted` `text-faint` |
| 主色按钮 / 强 hover | `bg-primary` `hover:bg-primary-strong` `text-on-primary` |
| 主色柔底（chip、图标底、列表 hover） | `bg-primary-soft`（10%）`bg-primary-softer`（6%） |
| 主色文字 / 描边按钮 | `text-primary` `border-primary` |
| 成功 / 危险 / 警告 / 强调 | `bg-success` `bg-danger` `bg-warning` `bg-accent`（+ `*-soft` 柔底版） |
| 分组淡彩 | `bg-lilac`（+ `lilac-soft`）`bg-mint` `bg-butter` `bg-coral` |
| 描边（1px 细线） | `border-hairline` `border-hairline-strong` |
| 导航层 | `bg-nav` `text-nav-ink` `text-nav-muted` |
| 圆角 | `rounded-card`（卡片）`rounded-btn`（按钮/chip）`rounded-input`（输入）`rounded-pill`（胶囊/圆） |
| 阴影 | `shadow-card` `shadow-card-hover` `shadow-btn` `shadow-float`（浮层/底栏） |
| 字体 | `font-body`（默认继承）标题自动 `h1/h2/h3` 走 `font-display`（warm 主题下为衬线） |

**禁止**：`bg-primary/50` 之类的透明度修饰符（值为纯 var() 字符串，不支持）。需要半透明用 `*-soft` 令牌。

## 从旧样式迁移的映射表

| 旧 | 新 |
|---|---|
| `bg-warm-bg` | `bg-canvas` |
| `bg-warm-light`（输入底/容器/hover） | `bg-primary-soft`（较重）或 `bg-primary-softer`（浅） |
| `bg-warm-light/40` 等透明变体 | `bg-primary-softer` |
| `bg-warm-primary` + `text-white`（按钮） | `bg-primary text-on-primary shadow-btn` |
| `bg-warm-primary`（非按钮色块） | `bg-primary text-on-primary` |
| `bg-warm-dark` / `hover:bg-amber-700` | `bg-primary-strong` / `hover:bg-primary-strong` |
| `text-warm-primary` / `text-warm-dark` | `text-primary` |
| `border-2 border-warm-light` | `border border-hairline` |
| `border-warm-primary` | `border-primary`（同时去掉 `border-2`） |
| `focus:border-warm-primary` | `focus:border-primary` |
| `bg-white`（卡片） | `bg-card`（通常加 `shadow-card`） |
| `bg-white/60~80`（浅 chip） | `bg-card-soft` |
| `text-gray-900/800` | `text-ink` |
| `text-gray-700/600` | `text-ink`（主要）或 `text-muted`（次要） |
| `text-gray-500` | `text-muted` |
| `text-gray-400` | `text-faint` |
| `border-gray-200/300` | `border-hairline` |
| `bg-red-50 border-red-300 text-red-700`（错误框） | `bg-danger-soft text-danger`（去边框） |
| `bg-green-50/emerald-50 text-emerald-700`（成功） | `bg-success-soft text-success` |
| `bg-amber-50 border-amber-300`（警告） | `bg-warning-soft text-warning`；中性提示用 `bg-butter` |
| `bg-rose-500`（徽章） | `bg-danger text-on-primary` |
| `text-rose-600 / text-red-600` | `text-danger` |
| `from-sky-50 to-indigo-50 border-indigo-200` | `bg-lilac-soft`（去渐变去边框） |
| `from-rose-50 to-amber-50 border-rose-200` | `bg-accent-soft` |
| `from-amber-50 to-orange-50 border-warm-primary` | `bg-primary-soft` |
| 其它任何 `from-*/to-*/via-*` 渐变 | 对应语义柔底单色 |
| `rounded-3xl/2xl`（卡片） | `rounded-card` |
| `rounded-xl`（按钮） | `rounded-btn` |
| `rounded-xl`（input/select/textarea） | `rounded-input` |
| `rounded-lg`（小 chip） | `rounded-btn` 或 `rounded-pill` |
| `rounded-full`（头像/圆点） | `rounded-pill` |
| `shadow-sm` / `shadow-md/lg` | `shadow-card` |
| `shadow-xl/2xl`（弹层） | `shadow-float` |
| focus ring | `focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)]` |

## 图标

- 用 `lucide-react`（已安装）。emoji 只允许出现在聊天内容/文案里，不允许当 UI 图标。
- 常用映射：💬MessageCircle 📞Phone ❤️Heart 💌Mail 🌊Waves 📗BookOpen 👤User ⚙Settings 📚Library 👨‍👩‍👧Users 🌻Flower2 🐶Dog ✍️PenLine 🔄RefreshCw 🎤Mic 🔊Volume2 🔇VolumeX 🎵Music 🎥Video ✕X ✓Check ⏳Hourglass 🔒Lock
- 用法：`<Icon aria-hidden className="h-5 w-5" />`，容器加 `inline-flex items-center gap-1.5`。

## 硬性规则

1. 大触控目标不缩水：`min-h-[44px]` 以上全部保留。
2. 所有 aria-* / role / 无障碍属性保留。
3. 不改任何逻辑、state、API 调用、事件处理；只动 className、图标、必要的 import。
4. 高对比模式（黑底黄字）由 globals.css 用语义类选择器覆盖，勿在组件内另写。
5. 主色按钮 hover 加深用 `hover:bg-primary-strong`，不要引入新颜色。

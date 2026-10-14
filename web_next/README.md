# 老人情感陪伴 AI - 前端 (Next.js 14)

基于 Next.js 14 (App Router) + TypeScript + Tailwind CSS + Zustand + Recharts 的老人友好前端。

## 启动

```bash
cd web_next
npm install
npm run dev
```

打开 http://localhost:3000 （后端需运行在 http://localhost:8000）

生产模式：

```bash
npm run build
npm start
```

## 功能页面

- `/login` `/register` — 登录/注册（老人/家属角色）
- `/` — 聊天主页（文字 + 大🎤语音输入 + AI 回复 TTS 播报 + 推荐卡片）
- `/profile` — 老人画像编辑 + 长期记忆管理
- `/emotion` — 情绪历史折线图（recharts）
- `/family` — 家属看板：绑定老人、查看老人情绪历史

## 老人友好设计

- 默认字号 18px，可在右上角切换 18 / 20 / 24
- 高对比度模式（黑底黄字）
- 所有按钮最小 48px 高
- 主色暖橙 `#F59E0B`，背景米白 `#FFFBEB`

## 技术要点

- `src/lib/api.ts`：fetch 封装，自动带 JWT，401 自动刷新 token 并重试，刷新失败跳登录
- `src/stores/auth.ts` / `settings.ts`：zustand + localStorage 持久化
- `next.config.js`：`/api/v1/*` 代理到后端 `:8000`
- PWA：`public/manifest.json` + `public/sw.js`（仅缓存静态资源，API 不缓存）

## 依赖

`next 14.2.5`, `react 18`, `typescript 5`, `tailwindcss 3.4`, `zustand 4.5`, `recharts 2.12`

import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SettingsProvider } from '@/components/SettingsProvider';
import { NavBar } from '@/components/NavBar';
import { CareAlertModal } from '@/components/CareAlertModal';
import { LetterArrivalModal } from '@/components/LetterArrivalModal';

// 全站为客户端交互应用（登录态存 localStorage），
// 禁止静态预渲染被长期缓存，避免发版后客户端仍加载旧页面/旧 chunk。
export const dynamic = 'force-dynamic';

export const metadata: Metadata = {
  title: '老人情感陪伴 AI',
  description: '温暖的陪伴，随时光与记忆同行',
  manifest: '/manifest.json',
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  maximumScale: 5,
  // 会被 SettingsProvider 按当前主题动态改写；这里是默认主题（粉彩）的顶栏色
  themeColor: '#fffdf9',
  // 让页面铺到 iPhone 刘海/底部横条下面，再由 safe-area 变量补内边距
  viewportFit: 'cover',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <head>
        {/* 首帧前恢复主题/字号偏好，避免刷新时先闪默认样式（zustand persist 存储格式） */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var raw=localStorage.getItem('settings-storage');if(!raw)return;var s=JSON.parse(raw).state||{};var r=document.documentElement;['pastel','soft','warm'].forEach(function(t){r.classList.remove('theme-'+t)});r.classList.add('theme-'+(s.theme==='soft'||s.theme==='warm'?s.theme:'pastel'));r.classList.remove('font-normal','font-large','font-xlarge');r.classList.add('font-'+(s.fontSize||'normal'));if(s.highContrast)r.classList.add('high-contrast');}catch(e){}})();`,
          }}
        />
      </head>
      <body className="bg-canvas">
        {/* 放在最前：先摘掉历史遗留的 Service Worker 与其缓存，再渲染应用（本地事故修复，勿删） */}
        <ServiceWorkerCleanup />
        <SettingsProvider>
          <NavBar />
          <CareAlertModal />
          <LetterArrivalModal />
          {/* app-main 由远程 design system 提供底部 TabBar 留白；NavBar 已内置 TabBar 与高度同步 */}
          <main className="app-main">{children}</main>
        </SettingsProvider>
      </body>
    </html>
  );
}

/**
 * 不再注册 Service Worker，只保留「清理」逻辑。
 *
 * 原因（2026-10-30 事故）：SW 曾把 Next App Router 的 RSC 数据请求（URL 带 ?_rsc=）
 * 当静态资源缓存，导致前端拿到的 RSC 与当前 chunk 结构不匹配，
 * 抛 `TypeError: Cannot read properties of null (reading 'get')` 白屏。
 * 本项目是局域网演示，离线缓存没有收益，索性停掉。
 *
 * 这里保留注销 + 清缓存，是为了把历史上已被注册的 SW 从用户设备上摘掉
 * （包括小米浏览器这类更新很慢的实现）。脚本放在 body 最前，尽早执行。
 */
function ServiceWorkerCleanup() {
  const code = `
    if (typeof window !== 'undefined') {
      try {
        if ('serviceWorker' in navigator) {
          navigator.serviceWorker.getRegistrations().then(function (items) {
            return Promise.all(items.map(function (item) { return item.unregister(); }));
          }).catch(function () {});
        }
        if ('caches' in window) {
          caches.keys().then(function (keys) {
            return Promise.all(
              keys.filter(function (k) { return k.indexOf('elderly-companion-') === 0; })
                  .map(function (k) { return caches.delete(k); })
            );
          }).catch(function () {});
        }
      } catch (e) {}
    }
  `;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}

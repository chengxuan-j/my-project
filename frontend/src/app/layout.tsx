import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SettingsProvider } from '@/components/SettingsProvider';
import { NavBar } from '@/components/NavBar';
import { NavHeightSync } from '@/components/NavHeightSync';
import { CareAlertModal } from '@/components/CareAlertModal';
import { LetterArrivalModal } from '@/components/LetterArrivalModal';
import { BottomTabBar } from '@/components/BottomTabBar';

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
  themeColor: '#F59E0B',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-warm-bg">
        {/* 放在最前：先摘掉历史遗留的 Service Worker 与其缓存，再渲染应用 */}
        <ServiceWorkerCleanup />
        <SettingsProvider>
          <NavBar />
          <NavHeightSync />
          <CareAlertModal />
          <LetterArrivalModal />
          {/* 移动端底部 tab 占位留白（桌面端无 tab，保持原 pb-8） */}
          <main className="pb-24 md:pb-8">{children}</main>
          <BottomTabBar />
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

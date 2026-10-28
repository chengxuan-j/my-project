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
  themeColor: '#F59E0B',
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
      <body className="bg-warm-bg">
        <SettingsProvider>
          <NavBar />
          <CareAlertModal />
          <LetterArrivalModal />
          <main className="app-main">{children}</main>
          <ServiceWorkerRegister />
        </SettingsProvider>
      </body>
    </html>
  );
}

function ServiceWorkerRegister() {
  const code = `
    if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        if (${JSON.stringify(process.env.NODE_ENV)} === 'development') {
          navigator.serviceWorker.getRegistrations().then((items) =>
            Promise.all(items.map((item) => item.unregister()))
          ).catch(() => {});
          if ('caches' in window) {
            caches.keys().then((keys) =>
              Promise.all(keys.filter((key) => key.startsWith('elderly-companion-')).map((key) => caches.delete(key)))
            ).catch(() => {});
          }
        } else {
          navigator.serviceWorker.register('/sw.js').catch(() => {});
        }
      });
    }
  `;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}

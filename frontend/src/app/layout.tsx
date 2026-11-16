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

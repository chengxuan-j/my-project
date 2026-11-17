'use client';

import { useEffect } from 'react';

/**
 * 把导航栏的真实高度写进 CSS 变量 --nav-h。
 *
 * 原因：导航在窄屏（手机）会从一行换行成两行，高度远超桌面端的 72px。
 * 页面若写死 calc(100vh - 72px)，底部输入框/话筒会被推出视口。
 * 页面应改用 calc(100dvh - var(--nav-h, 72px))。
 */
export function NavHeightSync() {
  useEffect(() => {
    const apply = () => {
      const header = document.querySelector('header');
      const h = header instanceof HTMLElement ? header.offsetHeight : 0;
      document.documentElement.style.setProperty('--nav-h', `${h}px`);
    };

    // 首帧 header 可能还没挂上，下一帧再量一次
    apply();
    const raf = requestAnimationFrame(apply);

    let ro: ResizeObserver | null = null;
    const header = document.querySelector('header');
    if (header && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(apply);
      ro.observe(header);
    }

    window.addEventListener('resize', apply);
    window.addEventListener('orientationchange', apply);
    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
      window.removeEventListener('resize', apply);
      window.removeEventListener('orientationchange', apply);
    };
  }, []);

  return null;
}

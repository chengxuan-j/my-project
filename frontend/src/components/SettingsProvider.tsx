'use client';

import { useEffect } from 'react';
import { useSettingsStore } from '@/stores/settings';

/** 主题对应的手机浏览器地址栏颜色（theme-color meta） */
const THEME_COLOR: Record<string, string> = {
  pastel: '#fffdf9',
  soft: '#ffffff',
  warm: '#e8ded1',
};

/** 字号 / 主题 / 高对比都落在 <html> 的 class 上，store 只存偏好 */
export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const fontSize = useSettingsStore((s) => s.fontSize);
  const theme = useSettingsStore((s) => s.theme);
  const highContrast = useSettingsStore((s) => s.highContrast);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('font-normal', 'font-large', 'font-xlarge');
    root.classList.add(`font-${fontSize}`);
    root.classList.remove('theme-pastel', 'theme-soft', 'theme-warm');
    root.classList.add(`theme-${theme}`);
    root.classList.toggle('high-contrast', highContrast);
  }, [fontSize, theme, highContrast]);

  // 高对比模式下地址栏也要跟黑底走
  useEffect(() => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    meta.setAttribute('content', highContrast ? '#000000' : THEME_COLOR[theme] ?? '#fffdf9');
  }, [theme, highContrast]);

  return <>{children}</>;
}


'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type FontSize = 'normal' | 'large' | 'xlarge';
/** 三套视觉主题，对应 globals.css 里 html.theme-* 的令牌覆盖 */
export type ThemeId = 'pastel' | 'soft' | 'warm';

interface SettingsState {
  fontSize: FontSize;
  theme: ThemeId;
  highContrast: boolean;
  autoTTS: boolean;
  setFontSize: (size: FontSize) => void;
  setTheme: (theme: ThemeId) => void;
  toggleHighContrast: () => void;
  toggleAutoTTS: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      fontSize: 'normal',
      theme: 'pastel',
      highContrast: false,
      autoTTS: true,
      setFontSize: (fontSize) => set({ fontSize }),
      setTheme: (theme) => set({ theme }),
      toggleHighContrast: () => set((s) => ({ highContrast: !s.highContrast })),
      toggleAutoTTS: () => set((s) => ({ autoTTS: !s.autoTTS })),
    }),
    { name: 'settings-storage' }
  )
);

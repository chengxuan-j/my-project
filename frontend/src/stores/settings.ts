'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type FontSize = 'normal' | 'large' | 'xlarge';

interface SettingsState {
  fontSize: FontSize;
  highContrast: boolean;
  autoTTS: boolean;
  setFontSize: (size: FontSize) => void;
  toggleHighContrast: () => void;
  toggleAutoTTS: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      fontSize: 'normal',
      highContrast: false,
      autoTTS: true,
      setFontSize: (fontSize) => set({ fontSize }),
      toggleHighContrast: () => set((s) => ({ highContrast: !s.highContrast })),
      toggleAutoTTS: () => set((s) => ({ autoTTS: !s.autoTTS })),
    }),
    { name: 'settings-storage' }
  )
);

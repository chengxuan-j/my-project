'use client';

import { useEffect } from 'react';
import { useSettingsStore } from '@/stores/settings';

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  const fontSize = useSettingsStore((s) => s.fontSize);
  const highContrast = useSettingsStore((s) => s.highContrast);

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('font-normal', 'font-large', 'font-xlarge');
    root.classList.add(`font-${fontSize}`);
    root.classList.toggle('high-contrast', highContrast);
  }, [fontSize, highContrast]);

  return <>{children}</>;
}

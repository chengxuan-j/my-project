'use client';

import { useSettingsStore, FontSize } from '@/stores/settings';

const OPTIONS: { value: FontSize; label: string; title: string }[] = [
  { value: 'normal', label: 'A', title: '标准字号 18px' },
  { value: 'large', label: 'A+', title: '大字号 20px' },
  { value: 'xlarge', label: 'A++', title: '特大字号 24px' },
];

/**
 * 字号切换。variant 仅为兼容旧调用点保留：导航栏与抽屉现在都是浅色底，
 * 两种场景共用同一套样式。
 */
export function FontSizeToggle({ variant = 'onPrimary' }: { variant?: 'onPrimary' | 'onLight' }) {
  void variant;
  const { fontSize, setFontSize } = useSettingsStore();

  return (
    <div
      className="flex gap-1 rounded-lg p-1 bg-primary-soft"
      role="group"
      aria-label="字号"
    >
      {OPTIONS.map((opt) => {
        const active = fontSize === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => setFontSize(opt.value)}
            title={opt.title}
            aria-pressed={active}
            className={`min-h-[44px] min-w-[44px] rounded-md px-2 font-bold ${
              active ? 'bg-primary text-on-primary' : 'text-muted hover:bg-primary-softer'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

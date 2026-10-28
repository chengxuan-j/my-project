'use client';

import { useSettingsStore, FontSize } from '@/stores/settings';

const OPTIONS: { value: FontSize; label: string; title: string }[] = [
  { value: 'normal', label: 'A', title: '标准字号 18px' },
  { value: 'large', label: 'A+', title: '大字号 20px' },
  { value: 'xlarge', label: 'A++', title: '特大字号 24px' },
];

/**
 * 字号切换。
 *
 * 两种配色：`onPrimary` 用于橙色导航栏（默认），`onLight` 用于白色抽屉/卡片。
 * 之前只有白色文字一版，放进白底「更多」抽屉里会完全看不见。
 */
export function FontSizeToggle({ variant = 'onPrimary' }: { variant?: 'onPrimary' | 'onLight' }) {
  const { fontSize, setFontSize } = useSettingsStore();
  const onLight = variant === 'onLight';

  return (
    <div
      className={`flex gap-1 rounded-lg p-1 ${onLight ? 'bg-warm-light' : 'bg-white/20'}`}
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
              active
                ? onLight
                  ? 'bg-warm-primary text-white'
                  : 'bg-white text-warm-primary'
                : onLight
                  ? 'text-warm-dark hover:bg-white'
                  : 'text-white hover:bg-white/30'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

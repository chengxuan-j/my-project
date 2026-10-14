'use client';

import { useSettingsStore, FontSize } from '@/stores/settings';

const OPTIONS: { value: FontSize; label: string; title: string }[] = [
  { value: 'normal', label: 'A', title: '标准字号 18px' },
  { value: 'large', label: 'A+', title: '大字号 20px' },
  { value: 'xlarge', label: 'A++', title: '特大字号 24px' },
];

export function FontSizeToggle() {
  const { fontSize, setFontSize } = useSettingsStore();
  return (
    <div className="flex gap-1 bg-white/20 rounded-lg p-1">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => setFontSize(opt.value)}
          title={opt.title}
          aria-pressed={fontSize === opt.value}
          className={`min-h-[40px] min-w-[44px] rounded-md px-2 font-bold ${
            fontSize === opt.value
              ? 'bg-white text-warm-primary'
              : 'text-white hover:bg-white/30'
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

'use client';

import { useSettingsStore, ThemeId } from '@/stores/settings';

const OPTIONS: { value: ThemeId; label: string; title: string; swatch: string }[] = [
  { value: 'pastel', label: '粉彩', title: '粉彩主题 · 暖奶油底', swatch: 'linear-gradient(135deg, #fff8f0 40%, #66508f 40%)' },
  { value: 'soft', label: '雾白', title: '雾白主题 · 低饱和靛蓝', swatch: 'linear-gradient(135deg, #f1f5f9 40%, #6366f1 40%)' },
  { value: 'warm', label: '陶土', title: '陶土主题 · 赤陶暖调', swatch: 'linear-gradient(135deg, #f5f0eb 40%, #c86a4a 40%)' },
];

/**
 * 主题切换。variant 仅为兼容旧调用点保留：导航栏与抽屉现在都是浅色底，
 * 两种场景共用同一套样式。
 */
export function ThemeToggle({ variant = 'onPrimary' }: { variant?: 'onPrimary' | 'onLight' }) {
  void variant;
  const { theme, setTheme } = useSettingsStore();

  return (
    <div
      className="flex gap-1 rounded-lg p-1 bg-primary-soft"
      role="group"
      aria-label="主题"
    >
      {OPTIONS.map((opt) => {
        const active = theme === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => setTheme(opt.value)}
            title={opt.title}
            aria-pressed={active}
            className={`flex min-h-[44px] flex-col items-center justify-center gap-0.5 rounded-md px-2 ${
              active ? 'bg-primary text-on-primary' : 'text-muted hover:bg-primary-softer'
            }`}
          >
            <span
              aria-hidden
              className={`h-3.5 w-6 rounded-sm ring-1 ${active ? 'ring-white/60' : 'ring-black/10'}`}
              style={{ background: opt.swatch }}
            />
            <span className="text-xs font-bold leading-none">{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}

'use client';

import { useEffect, useRef, useState } from 'react';
import { Contrast, Settings2, X } from 'lucide-react';
import { useSettingsStore } from '@/stores/settings';
import { FontSizeToggle } from './FontSizeToggle';
import { ThemeToggle } from './ThemeToggle';
import { DialectSwitch } from './DialectSwitch';

/**
 * 桌面端「设置」弹层：方言 / 字号 / 主题 / 高对比度。
 * 顶栏不再平铺这些控件，改为一个入口，导航只承担页面切换。
 */
export function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const { highContrast, toggleHighContrast } = useSettingsStore();
  const ref = useRef<HTMLDivElement>(null);

  // 点外部 / Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label="显示设置"
        title="显示设置：主题 / 字号 / 方言 / 高对比"
        className={`min-h-[44px] min-w-[44px] rounded-btn flex items-center justify-center gap-1.5 px-3 ${
          open ? 'bg-primary text-on-primary' : 'bg-primary-soft text-primary hover:bg-primary-softer'
        }`}
      >
        <Settings2 aria-hidden className="h-5 w-5" />
        <span className="text-sm font-medium hidden lg:inline">设置</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="显示设置"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-[340px] rounded-card bg-card border border-hairline shadow-float p-4"
        >
          <div className="flex items-center justify-between mb-3">
            <p className="text-base font-bold text-ink">显示设置</p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              aria-label="关闭"
              className="min-h-[36px] min-w-[36px] rounded-btn text-muted hover:bg-primary-soft flex items-center justify-center"
            >
              <X aria-hidden className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-sm text-muted">主题</p>
              <ThemeToggle />
            </div>
            <div>
              <p className="mb-1.5 text-sm text-muted">字号</p>
              <FontSizeToggle />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm text-muted">方言</span>
              <DialectSwitch />
            </div>
            <div className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5 text-sm text-muted">
                <Contrast aria-hidden className="h-4 w-4" />
                高对比度
              </span>
              <button
                type="button"
                onClick={toggleHighContrast}
                aria-pressed={highContrast}
                className={`min-h-[40px] px-4 rounded-btn text-sm font-bold ${
                  highContrast
                    ? 'bg-primary text-on-primary'
                    : 'bg-primary-soft text-primary'
                }`}
              >
                {highContrast ? '已开启' : '关闭'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

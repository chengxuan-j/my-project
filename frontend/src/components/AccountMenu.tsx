'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, LogOut, Plus, UserRound, Users } from 'lucide-react';
import type { Session, UserInfo } from '@/stores/auth';

interface Props {
  user: UserInfo;
  sessions: Session[];
  activeId: string | null;
  onSwitch: (s: Session) => void;
  onLogout: () => void;
}

/**
 * 桌面端账号菜单：当前身份 + 多账号切换 + 添加账号 + 退出。
 * 顶栏只显示一个身份 chip，细节收进菜单。
 */
export function AccountMenu({ user, sessions, activeId, onSwitch, onLogout }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

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
        aria-haspopup="menu"
        aria-expanded={open}
        className={`min-h-[44px] pl-3 pr-2.5 rounded-btn flex items-center gap-2 text-sm font-medium ${
          open ? 'bg-primary text-on-primary' : 'bg-primary-soft text-primary hover:bg-primary-softer'
        }`}
      >
        <UserRound aria-hidden className="h-4 w-4" />
        <span className="max-w-[120px] truncate">{user.name || user.username}</span>
        <ChevronDown aria-hidden className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="账号"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-[260px] rounded-card bg-card border border-hairline shadow-float p-2"
        >
          {sessions.map((s) => {
            const active = s.key === activeId;
            return (
              <button
                key={s.key}
                role="menuitemradio"
                aria-checked={active}
                onClick={() => {
                  onSwitch(s);
                  setOpen(false);
                }}
                className={`w-full min-h-[44px] px-3 rounded-btn flex items-center gap-2 text-sm ${
                  active ? 'bg-primary-soft text-primary font-bold' : 'text-ink hover:bg-primary-softer'
                }`}
              >
                <span className="flex h-7 w-7 items-center justify-center rounded-pill bg-primary-soft text-primary shrink-0">
                  {s.user.role === 'family' ? <Users className="h-3.5 w-3.5" /> : <UserRound className="h-3.5 w-3.5" />}
                </span>
                <span className="truncate">{s.user.name || s.user.username}</span>
                {active && <Check aria-hidden className="ml-auto h-4 w-4" />}
              </button>
            );
          })}

          <div className="my-1.5 border-t border-hairline" />
          <Link
            href="/login"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="w-full min-h-[44px] px-3 rounded-btn flex items-center gap-2 text-sm text-ink hover:bg-primary-softer"
          >
            <Plus aria-hidden className="h-4 w-4 text-muted" />
            添加账号
          </Link>
          <button
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="w-full min-h-[44px] px-3 rounded-btn flex items-center gap-2 text-sm text-danger hover:bg-danger-soft"
          >
            <LogOut aria-hidden className="h-4 w-4" />
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}

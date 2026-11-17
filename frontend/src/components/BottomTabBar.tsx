'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuthStore } from '@/stores/auth';
import { useCareStore } from '@/stores/care';

// 微信式底部导航：移动端只保留 4 个高频入口，低频功能收进「我的」页
const TABS_ELDERLY = [
  { href: '/', icon: '💬', label: '聊天' },
  { href: '/call', icon: '📞', label: '通话' },
  { href: '/care', icon: '❤️', label: '关怀' },
  { href: '/profile', icon: '👤', label: '我的' },
];

const TABS_FAMILY = [
  { href: '/family', icon: '👨‍👩‍👧', label: '家人' },
  { href: '/knowledge', icon: '📚', label: '知识库' },
  { href: '/account', icon: '⚙', label: '账号' },
];

export function BottomTabBar() {
  const pathname = usePathname();
  const user = useAuthStore((s) => s.user);
  const dueCount = useCareStore((s) => s.dueCount);

  // 登录/注册页不显示（与 NavBar 一致）
  if (pathname === '/login' || pathname === '/register') return null;

  const tabs = user?.role === 'family' ? TABS_FAMILY : TABS_ELDERLY;

  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-white border-t border-gray-200 pb-[env(safe-area-inset-bottom)]">
      <div className="flex">
        {tabs.map((t) => {
          const active = pathname === t.href;
          return (
            <Link
              key={t.href}
              href={t.href}
              aria-current={active ? 'page' : undefined}
              className={`relative flex-1 flex flex-col items-center justify-center gap-0.5 min-h-[56px] ${
                active ? 'text-warm-primary' : 'text-gray-500'
              }`}
            >
              <span className="text-xl leading-none">{t.icon}</span>
              <span className={`text-[11px] leading-none ${active ? 'font-bold' : ''}`}>
                {t.label}
              </span>
              {t.href === '/care' && dueCount > 0 && (
                <span
                  aria-label={`${dueCount} 条待处理提醒`}
                  className="absolute top-1.5 left-1/2 translate-x-3 min-w-[16px] h-[16px] px-1 rounded-full bg-rose-500 text-white text-[10px] font-bold flex items-center justify-center"
                >
                  {dueCount}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

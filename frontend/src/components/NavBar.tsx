'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore, Session } from '@/stores/auth';
import { authApi } from '@/lib/api';
import { FontSizeToggle } from './FontSizeToggle';
import { DialectSwitch } from './DialectSwitch';
import { useSettingsStore } from '@/stores/settings';
import { useCareStore } from '@/stores/care';

const NAV_ITEMS_ELDERLY = [
  { href: '/', label: '💬 聊天' },
  { href: '/call', label: '📞 通话' },
  { href: '/care', label: '❤️ 关怀' },
  { href: '/letters', label: '💌 信笺' },
  { href: '/journey', label: '🌊 人生河' },
  { href: '/book', label: '📗 人生之书' },
  { href: '/profile', label: '👤 我的' },
  { href: '/account', label: '⚙ 账号' },
];

const NAV_ITEMS_FAMILY = [
  { href: '/family', label: '👨‍👩‍👧 我的家人' },
  { href: '/knowledge', label: '📚 知识库' },
  { href: '/account', label: '⚙ 账号' },
];

export function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, sessions, activeId, switchAccount, removeAccount } = useAuthStore();
  const { highContrast, toggleHighContrast } = useSettingsStore();
  const dueCount = useCareStore((s) => s.dueCount);

  // 手机端：方言/字号/对比/账号/退出 收进折叠面板，否则导航会占掉 1/4 屏
  // 必须放在下方提前 return 之前——hooks 不能出现在条件 return 后面，
  // 否则从 /login 切到其他页时 hooks 数量变化，报 "Rendered more hooks"（2026-11-04 手机端白屏根因）
  const [toolsOpen, setToolsOpen] = useState(false);

  // 旧版本登录缓存里没有 name，补拉一次，避免导航一直显示登录名
  useEffect(() => {
    if (!user || user.role !== 'elderly' || user.name) return;
    authApi
      .me()
      .then((me) => {
        if (me.name) useAuthStore.getState().updateUserName(me.name);
      })
      .catch(() => undefined);
  }, [user]);

  // 登录/注册页不显示导航
  if (pathname === '/login' || pathname === '/register') return null;

  const homeOf = (role?: string) => (role === 'family' ? '/family' : '/');

  const handleSwitch = (s: Session) => {
    switchAccount(s.key);
    router.push(homeOf(s.user.role));
  };

  const handleLogout = () => {
    const remaining = sessions.filter((s) => s.key !== activeId);
    removeAccount(activeId ?? '');
    router.push(remaining.length > 0 ? homeOf(remaining[0].user.role) : '/login');
  };

  // 按角色选菜单
  const navItems = user?.role === 'family' ? NAV_ITEMS_FAMILY : NAV_ITEMS_ELDERLY;
  const homeHref = user?.role === 'family' ? '/family' : '/';

  // 手机端：方言/字号/对比/账号/退出 收进折叠面板
  const tools = (
    <>
      <DialectSwitch />
      <FontSizeToggle />
      <button
        onClick={toggleHighContrast}
        aria-pressed={highContrast}
        className="min-h-[48px] px-3 rounded-lg bg-warm-dark hover:bg-amber-700 text-base"
        title="高对比度模式"
      >
        {highContrast ? '🌙 对比' : '👁 对比'}
      </button>
      {user ? (
        <>
          {/* 多账号身份切换：同一浏览器可同时登录老人 / 家属 */}
          <div className="flex items-center gap-1">
            {sessions.map((s) => (
              <button
                key={s.key}
                onClick={() => handleSwitch(s)}
                aria-pressed={s.key === activeId}
                title={`切换到 ${s.user.name || s.user.username}`}
                className={`min-h-[48px] px-3 rounded-lg text-sm flex items-center gap-1 ${
                  s.key === activeId
                    ? 'bg-white text-warm-primary font-bold'
                    : 'bg-warm-dark hover:bg-amber-700'
                }`}
              >
                {s.user.role === 'family' ? '👨‍👩‍👧' : '👴'}
                {s.user.name || s.user.username}
              </button>
            ))}
            <Link
              href="/login"
              title="添加 / 登录另一个账号"
              className="min-h-[48px] px-3 rounded-lg bg-warm-dark hover:bg-amber-700 text-sm flex items-center"
            >
              ＋账号
            </Link>
          </div>
          <button
            onClick={handleLogout}
            className="min-h-[48px] px-4 rounded-lg bg-white text-warm-primary font-bold hover:bg-warm-light text-base"
          >
            退出
          </button>
        </>
      ) : (
        <Link
          href="/login"
          className="min-h-[48px] px-4 rounded-lg bg-white text-warm-primary font-bold hover:bg-warm-light text-base flex items-center"
        >
          登录
        </Link>
      )}
    </>
  );

  return (
    <header className="bg-warm-primary text-white shadow-md sticky top-0 z-40">
      <div className="max-w-5xl mx-auto px-3 py-2 flex flex-nowrap md:flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-4 min-w-0 flex-1 md:flex-none">
          {/* 中文在窄屏会被逐字断行，必须 nowrap；菜单放不下时横向滚动而不是换行 */}
          <Link href={homeHref} className="text-xl font-bold tracking-wide whitespace-nowrap shrink-0">
            🌻 陪伴 AI
          </Link>
          <nav className="hidden md:flex gap-1 overflow-x-auto whitespace-nowrap min-w-0">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`px-3 py-2 rounded-lg text-base font-medium min-h-[48px] flex items-center shrink-0 whitespace-nowrap ${
                  pathname === item.href
                    ? 'bg-white text-warm-primary'
                    : 'hover:bg-warm-dark'
                }`}
              >
                {item.label}
                {item.href === '/care' && dueCount > 0 && (
                  <span
                    aria-label={`${dueCount} 条待处理提醒`}
                    className="ml-1 inline-flex items-center justify-center min-w-[22px] h-[22px] px-1 rounded-full bg-rose-500 text-white text-xs font-bold"
                  >
                    {dueCount}
                  </span>
                )}
              </Link>
            ))}
          </nav>
        </div>

        {/* 桌面端：控件直接铺在导航栏上 */}
        <div className="hidden md:flex items-center gap-2 flex-wrap whitespace-nowrap">{tools}</div>

        {/* 手机端：一个设置按钮，点开才是那一堆控件 */}
        <button
          type="button"
          onClick={() => setToolsOpen((o) => !o)}
          aria-expanded={toolsOpen}
          aria-label="设置与账号"
          className="md:hidden min-h-[48px] px-3 rounded-lg bg-warm-dark shrink-0 text-base"
        >
          {toolsOpen ? '✕' : '⚙'}
        </button>
      </div>

      {/* 移动端导航已改为底部 TabBar（见 BottomTabBar），这里不再铺 8 宫格菜单 */}

      {toolsOpen && (
        <div className="md:hidden border-t border-white/25 px-4 py-3 flex flex-wrap items-center gap-2 whitespace-nowrap">
          {tools}
        </div>
      )}
    </header>
  );
}

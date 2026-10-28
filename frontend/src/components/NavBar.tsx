'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuthStore, Session } from '@/stores/auth';
import { authApi } from '@/lib/api';
import { FontSizeToggle } from './FontSizeToggle';
import { DialectSwitch } from './DialectSwitch';
import { useSettingsStore } from '@/stores/settings';
import { useCareStore } from '@/stores/care';

interface NavItem {
  href: string;
  label: string;
  icon: string;
}

const NAV_ITEMS_ELDERLY: NavItem[] = [
  { href: '/', label: '聊天', icon: '💬' },
  { href: '/call', label: '通话', icon: '📞' },
  { href: '/care', label: '关怀', icon: '❤️' },
  { href: '/letters', label: '信笺', icon: '💌' },
  { href: '/journey', label: '人生河', icon: '🌊' },
  { href: '/book', label: '人生之书', icon: '📗' },
  { href: '/profile', label: '我的', icon: '👤' },
  { href: '/account', label: '账号', icon: '⚙' },
];

const NAV_ITEMS_FAMILY: NavItem[] = [
  { href: '/family', label: '我的家人', icon: '👨‍👩‍👧' },
  { href: '/knowledge', label: '知识库', icon: '📚' },
  { href: '/account', label: '账号', icon: '⚙' },
];

/** 手机底部 TabBar 只放最常用的前 N 个，其余收进「更多」 */
const MOBILE_PRIMARY_COUNT = 4;

export function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, sessions, activeId, switchAccount, removeAccount } = useAuthStore();
  const { highContrast, toggleHighContrast } = useSettingsStore();
  const dueCount = useCareStore((s) => s.dueCount);
  const headerRef = useRef<HTMLElement>(null);
  const tabbarRef = useRef<HTMLElement>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

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

  // 换页面就收起「更多」抽屉，否则点完菜单抽屉还盖在新页面上
  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);

  // 抽屉打开时锁住背景滚动，避免老人在抽屉后面误滚页面
  useEffect(() => {
    if (!sheetOpen) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, [sheetOpen]);

  /**
   * 把导航的实际高度同步给 CSS 变量。
   *
   * 高度不能写死：字号放大、菜单换行都会改变它，而聊天页/通话页要按
   * 「一屏减导航」算高度，算错了输入框就会被顶出可视区。
   */
  useEffect(() => {
    const sync = (el: HTMLElement | null, cssVar: string) => {
      if (!el) return () => undefined;
      const write = () => {
        const h = Math.round(el.getBoundingClientRect().height);
        // 高度 0 说明当前断点下这块是隐藏的（如桌面端的 TabBar）：
        // 必须把变量撤掉，否则会残留上一个断点的值，页面底部空出一截。
        if (h > 0) document.documentElement.style.setProperty(cssVar, `${h}px`);
        else document.documentElement.style.removeProperty(cssVar);
      };
      write();
      const ro = new ResizeObserver(write);
      ro.observe(el);
      return () => ro.disconnect();
    };

    const stopHeader = sync(headerRef.current, '--app-header-h');
    const stopTabbar = sync(tabbarRef.current, '--app-tabbar-h');
    return () => {
      stopHeader();
      stopTabbar();
    };
  }, [pathname, user, sessions.length]);

  // 登录/注册页不显示导航
  if (pathname === '/login' || pathname === '/register') return null;

  const homeOf = (role?: string) => (role === 'family' ? '/family' : '/');

  const handleSwitch = (s: Session) => {
    switchAccount(s.key);
    setSheetOpen(false);
    router.push(homeOf(s.user.role));
  };

  const handleLogout = () => {
    const remaining = sessions.filter((s) => s.key !== activeId);
    removeAccount(activeId ?? '');
    setSheetOpen(false);
    router.push(remaining.length > 0 ? homeOf(remaining[0].user.role) : '/login');
  };

  // 按角色选菜单
  const isFamily = user?.role === 'family';
  const navItems = isFamily ? NAV_ITEMS_FAMILY : NAV_ITEMS_ELDERLY;
  const homeHref = isFamily ? '/family' : '/';
  const primaryItems = isFamily ? navItems : navItems.slice(0, MOBILE_PRIMARY_COUNT);
  const restItems = isFamily ? [] : navItems.slice(MOBILE_PRIMARY_COUNT);

  const badge = (href: string) => (href === '/care' && dueCount > 0 ? dueCount : 0);

  return (
    <>
      <header
        ref={headerRef}
        className="bg-warm-primary text-white shadow-md sticky top-0 z-40"
      >
        {/* ---------- 手机顶栏：只留品牌 + 更多 ---------- */}
        <div className="md:hidden min-h-[56px] px-4 py-2 flex items-center justify-between gap-3">
          <Link href={homeHref} className="text-xl font-bold tracking-wide">
            🌻 陪伴 AI
          </Link>
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={sheetOpen}
            className="min-h-[44px] px-4 rounded-xl bg-warm-dark text-base font-bold flex items-center gap-1"
          >
            ☰ 更多
          </button>
        </div>

        {/* ---------- 桌面导航：保持原有横排 ---------- */}
        <div className="hidden md:flex max-w-5xl mx-auto px-4 py-3 items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-4 min-w-0 flex-wrap">
            <Link href={homeHref} className="text-xl font-bold tracking-wide">
              🌻 陪伴 AI
            </Link>
            <nav className="flex gap-1 flex-wrap">
              {navItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={pathname === item.href ? 'page' : undefined}
                  className={`px-3 py-2 rounded-lg text-base font-medium min-h-[48px] flex items-center ${
                    pathname === item.href
                      ? 'bg-white text-warm-primary'
                      : 'hover:bg-warm-dark'
                  }`}
                >
                  <span aria-hidden className="mr-1">
                    {item.icon}
                  </span>
                  {item.label}
                  {badge(item.href) > 0 && (
                    <span
                      aria-label={`${badge(item.href)} 条待处理提醒`}
                      className="ml-1 inline-flex items-center justify-center min-w-[22px] h-[22px] px-1 rounded-full bg-rose-500 text-white text-xs font-bold"
                    >
                      {badge(item.href)}
                    </span>
                  )}
                </Link>
              ))}
            </nav>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
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
          </div>
        </div>
      </header>

      {/* ---------- 手机底部 TabBar ---------- */}
      <nav
        ref={tabbarRef}
        aria-label="主导航"
        className="md:hidden fixed inset-x-0 bottom-0 z-40 bg-white border-t-2 border-warm-light shadow-[0_-2px_10px_rgba(0,0,0,0.06)]"
        style={{ paddingBottom: 'var(--safe-bottom)' }}
      >
        <div
          className="grid"
          style={{
            gridTemplateColumns: `repeat(${primaryItems.length + 1}, minmax(0, 1fr))`,
          }}
        >
          {primaryItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={`relative flex flex-col items-center justify-center gap-0.5 py-1.5 min-h-[56px] ${
                  active ? 'text-warm-primary font-bold' : 'text-gray-500'
                }`}
              >
                <span aria-hidden className="text-xl leading-none">
                  {item.icon}
                </span>
                <span className="text-sm leading-tight">{item.label}</span>
                {badge(item.href) > 0 && (
                  <span
                    aria-label={`${badge(item.href)} 条待处理提醒`}
                    className="absolute top-1 right-1/2 translate-x-5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-rose-500 text-white text-[11px] font-bold"
                  >
                    {badge(item.href)}
                  </span>
                )}
                {active && (
                  <span
                    aria-hidden
                    className="absolute top-0 inset-x-3 h-[3px] rounded-b-full bg-warm-primary"
                  />
                )}
              </Link>
            );
          })}

          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={sheetOpen}
            className="flex flex-col items-center justify-center gap-0.5 py-1.5 min-h-[56px] text-gray-500"
          >
            <span aria-hidden className="text-xl leading-none">
              ⋯
            </span>
            <span className="text-sm leading-tight">更多</span>
          </button>
        </div>
      </nav>

      {/* ---------- 「更多」抽屉：其余菜单 + 偏好设置 + 账号 ---------- */}
      {sheetOpen && (
        <div className="md:hidden fixed inset-0 z-[75]">
          <div
            className="absolute inset-0 bg-black/45"
            onClick={() => setSheetOpen(false)}
            aria-hidden
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="更多功能"
            className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-3xl bg-white shadow-2xl"
            style={{ paddingBottom: 'calc(1rem + var(--safe-bottom))' }}
          >
            <div className="sticky top-0 bg-white px-5 pt-4 pb-2 flex items-center justify-between border-b border-warm-light">
              <p className="text-xl font-bold text-warm-dark">更多功能</p>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label="关闭"
                className="min-h-[44px] min-w-[44px] rounded-lg text-gray-500 text-xl"
              >
                ✕
              </button>
            </div>

            {restItems.length > 0 && (
              <div className="px-4 pt-3">
                <p className="px-1 pb-2 text-sm font-bold text-gray-400">全部功能</p>
                <div className="grid grid-cols-2 gap-2">
                  {restItems.map((item) => {
                    const active = pathname === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        className={`min-h-[64px] px-4 rounded-xl border-2 flex items-center gap-2 text-base ${
                          active
                            ? 'border-warm-primary bg-warm-light text-warm-dark font-bold'
                            : 'border-warm-light text-gray-800'
                        }`}
                      >
                        <span aria-hidden className="text-xl">
                          {item.icon}
                        </span>
                        {item.label}
                        {badge(item.href) > 0 && (
                          <span className="ml-auto inline-flex items-center justify-center min-w-[22px] h-[22px] px-1 rounded-full bg-rose-500 text-white text-xs font-bold">
                            {badge(item.href)}
                          </span>
                        )}
                      </Link>
                    );
                  })}
                </div>
              </div>
            )}

            <div className="px-4 pt-4">
              <p className="px-1 pb-2 text-sm font-bold text-gray-400">显示设置</p>
              <div className="rounded-xl border-2 border-warm-light p-3 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-base text-gray-700">字号</span>
                  <FontSizeToggle variant="onLight" />
                </div>
                {/* 家属账号没有方言设置，整行不渲染，免得只留一个空标题 */}
                {!isFamily && (
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <span className="text-base text-gray-700">方言</span>
                    <DialectSwitch />
                  </div>
                )}
                <div className="flex items-center justify-between gap-3">
                  <span className="text-base text-gray-700">高对比度</span>
                  <button
                    type="button"
                    onClick={toggleHighContrast}
                    aria-pressed={highContrast}
                    className={`min-h-[44px] px-4 rounded-lg border-2 font-bold ${
                      highContrast
                        ? 'border-warm-primary bg-warm-primary text-white'
                        : 'border-warm-light text-warm-dark'
                    }`}
                  >
                    {highContrast ? '已开启' : '关闭'}
                  </button>
                </div>
              </div>
            </div>

            <div className="px-4 pt-4">
              <p className="px-1 pb-2 text-sm font-bold text-gray-400">账号</p>
              {user ? (
                <div className="space-y-2">
                  {sessions.map((s) => (
                    <button
                      key={s.key}
                      onClick={() => handleSwitch(s)}
                      aria-pressed={s.key === activeId}
                      className={`w-full min-h-[56px] px-4 rounded-xl border-2 flex items-center gap-3 text-base ${
                        s.key === activeId
                          ? 'border-warm-primary bg-warm-light text-warm-dark font-bold'
                          : 'border-warm-light text-gray-800'
                      }`}
                    >
                      <span aria-hidden className="text-xl">
                        {s.user.role === 'family' ? '👨‍👩‍👧' : '👴'}
                      </span>
                      <span className="truncate">{s.user.name || s.user.username}</span>
                      {s.key === activeId && <span className="ml-auto">✓</span>}
                    </button>
                  ))}
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <Link
                      href="/login"
                      className="min-h-[52px] px-4 rounded-xl border-2 border-warm-primary text-warm-primary font-bold flex items-center justify-center"
                    >
                      ＋ 添加账号
                    </Link>
                    <button
                      type="button"
                      onClick={handleLogout}
                      className="min-h-[52px] px-4 rounded-xl border-2 border-rose-300 text-rose-600 font-bold"
                    >
                      退出登录
                    </button>
                  </div>
                </div>
              ) : (
                <Link
                  href="/login"
                  className="min-h-[56px] px-4 rounded-xl bg-warm-primary text-white font-bold flex items-center justify-center"
                >
                  去登录
                </Link>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

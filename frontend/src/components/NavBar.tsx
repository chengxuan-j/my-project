'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import {
  BookOpen,
  Check,
  Contrast,
  Flower2,
  Heart,
  Library,
  Mail,
  Menu,
  MessageCircle,
  MoreHorizontal,
  Phone,
  Plus,
  Settings,
  User,
  UserRound,
  Users,
  Waves,
  X,
  type LucideIcon,
} from 'lucide-react';
import { useAuthStore, Session } from '@/stores/auth';
import { authApi } from '@/lib/api';
import { FontSizeToggle } from './FontSizeToggle';
import { DialectSwitch } from './DialectSwitch';
import { ThemeToggle } from './ThemeToggle';
import { SettingsMenu } from './SettingsMenu';
import { AccountMenu } from './AccountMenu';
import { useSettingsStore } from '@/stores/settings';
import { useCareStore } from '@/stores/care';

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

const NAV_ITEMS_ELDERLY: NavItem[] = [
  { href: '/', label: '聊天', icon: MessageCircle },
  { href: '/call', label: '通话', icon: Phone },
  { href: '/care', label: '关怀', icon: Heart },
  { href: '/letters', label: '信笺', icon: Mail },
  { href: '/journey', label: '人生河', icon: Waves },
  { href: '/book', label: '人生之书', icon: BookOpen },
  { href: '/profile', label: '我的', icon: User },
  { href: '/account', label: '账号', icon: Settings },
];

const NAV_ITEMS_FAMILY: NavItem[] = [
  { href: '/family', label: '我的家人', icon: Users },
  { href: '/knowledge', label: '知识库', icon: Library },
  { href: '/account', label: '账号', icon: Settings },
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
        className="bg-nav text-nav-ink border-b border-hairline shadow-sm sticky top-0 z-40"
      >
        {/* ---------- 手机顶栏：品牌 + 更多 ---------- */}
        <div className="md:hidden min-h-[56px] px-4 py-2 flex items-center justify-between gap-3">
          <Link href={homeHref} className="flex items-center gap-2 text-xl font-bold tracking-wide">
            <Flower2 aria-hidden className="h-6 w-6 text-primary" />
            陪伴 AI
          </Link>
          <button
            type="button"
            onClick={() => setSheetOpen(true)}
            aria-haspopup="dialog"
            aria-expanded={sheetOpen}
            className="min-h-[44px] min-w-[44px] rounded-btn bg-primary-soft text-primary flex items-center justify-center gap-1 font-bold"
          >
            <Menu aria-hidden className="h-5 w-5" />
            更多
          </button>
        </div>

        {/* ---------- 桌面导航：品牌 · 主导航 · 设置 · 账号 ---------- */}
        <div className="hidden md:flex max-w-6xl mx-auto px-6 py-2.5 items-center gap-4">
          <Link href={homeHref} className="flex shrink-0 items-center gap-2 text-lg font-bold tracking-wide">
            <Flower2 aria-hidden className="h-6 w-6 text-primary" />
            陪伴 AI
          </Link>

          <nav aria-label="主导航" className="flex flex-1 min-w-0 flex-wrap gap-0.5">
            {navItems.map((item) => {
              const Icon = item.icon;
              const active = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? 'page' : undefined}
                  className={`relative px-2.5 py-2 rounded-btn text-sm font-medium min-h-[44px] flex items-center gap-1.5 whitespace-nowrap ${
                    active
                      ? 'bg-primary-soft text-primary font-bold'
                      : 'text-nav-muted hover:bg-primary-softer hover:text-primary'
                  }`}
                >
                  <Icon aria-hidden className="h-[17px] w-[17px]" />
                  {item.label}
                  {badge(item.href) > 0 && (
                    <span
                      aria-label={`${badge(item.href)} 条待处理提醒`}
                      className="ml-0.5 inline-flex items-center justify-center min-w-[20px] h-[20px] px-1 rounded-pill bg-danger text-on-primary text-[11px] font-bold"
                    >
                      {badge(item.href)}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>

          <div className="flex shrink-0 items-center gap-2">
            <SettingsMenu />
            {user ? (
              <AccountMenu
                user={user}
                sessions={sessions}
                activeId={activeId}
                onSwitch={handleSwitch}
                onLogout={handleLogout}
              />
            ) : (
              <Link
                href="/login"
                className="min-h-[44px] px-4 rounded-btn bg-primary text-on-primary font-bold shadow-btn hover:bg-primary-strong text-sm flex items-center"
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
        className="md:hidden fixed inset-x-0 bottom-0 z-40 bg-card border-t border-hairline shadow-float"
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
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? 'page' : undefined}
                className={`relative flex flex-col items-center justify-center gap-0.5 py-1.5 min-h-[56px] ${
                  active ? 'text-primary font-bold' : 'text-muted'
                }`}
              >
                <span className="relative">
                  <Icon aria-hidden className="h-5 w-5" />
                  {badge(item.href) > 0 && (
                    <span
                      aria-label={`${badge(item.href)} 条待处理提醒`}
                      className="absolute -top-1.5 -right-2.5 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-pill bg-danger text-on-primary text-[11px] font-bold"
                    >
                      {badge(item.href)}
                    </span>
                  )}
                </span>
                <span className="text-sm leading-tight">{item.label}</span>
                {active && (
                  <span
                    aria-hidden
                    className="absolute top-0 inset-x-3 h-[3px] rounded-b-pill bg-primary"
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
            className="flex flex-col items-center justify-center gap-0.5 py-1.5 min-h-[56px] text-muted"
          >
            <MoreHorizontal aria-hidden className="h-5 w-5" />
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
            className="absolute inset-x-0 bottom-0 max-h-[88dvh] overflow-y-auto rounded-t-card bg-card shadow-float"
            style={{ paddingBottom: 'calc(1rem + var(--safe-bottom))' }}
          >
            <div className="sticky top-0 bg-card px-5 pt-4 pb-2 flex items-center justify-between border-b border-hairline">
              <p className="text-xl font-bold text-ink">更多功能</p>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label="关闭"
                className="min-h-[44px] min-w-[44px] rounded-btn text-muted flex items-center justify-center"
              >
                <X aria-hidden className="h-5 w-5" />
              </button>
            </div>

            {restItems.length > 0 && (
              <div className="px-4 pt-3">
                <p className="px-1 pb-2 text-sm font-bold text-faint">全部功能</p>
                <div className="grid grid-cols-2 gap-2">
                  {restItems.map((item) => {
                    const active = pathname === item.href;
                    const Icon = item.icon;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        aria-current={active ? 'page' : undefined}
                        className={`min-h-[64px] px-4 rounded-btn border flex items-center gap-2 text-base ${
                          active
                            ? 'border-hairline-strong bg-primary-soft text-primary font-bold'
                            : 'border-hairline text-ink'
                        }`}
                      >
                        <Icon aria-hidden className="h-5 w-5 shrink-0" />
                        {item.label}
                        {badge(item.href) > 0 && (
                          <span className="ml-auto inline-flex items-center justify-center min-w-[22px] h-[22px] px-1 rounded-pill bg-danger text-on-primary text-xs font-bold">
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
              <p className="px-1 pb-2 text-sm font-bold text-faint">显示设置</p>
              <div className="rounded-card border border-hairline p-3 space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="text-base text-ink">主题</span>
                  <ThemeToggle />
                </div>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-base text-ink">字号</span>
                  <FontSizeToggle />
                </div>
                {/* 家属账号没有方言设置，整行不渲染，免得只留一个空标题 */}
                {!isFamily && (
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <span className="text-base text-ink">方言</span>
                    <DialectSwitch />
                  </div>
                )}
                <div className="flex items-center justify-between gap-3">
                  <span className="text-base text-ink">高对比度</span>
                  <button
                    type="button"
                    onClick={toggleHighContrast}
                    aria-pressed={highContrast}
                    className={`min-h-[44px] px-4 rounded-btn border font-bold ${
                      highContrast
                        ? 'border-transparent bg-primary text-on-primary'
                        : 'border-hairline-strong text-muted'
                    }`}
                  >
                    {highContrast ? '已开启' : '关闭'}
                  </button>
                </div>
              </div>
            </div>

            <div className="px-4 pt-4">
              <p className="px-1 pb-2 text-sm font-bold text-faint">账号</p>
              {user ? (
                <div className="space-y-2">
                  {sessions.map((s) => (
                    <button
                      key={s.key}
                      onClick={() => handleSwitch(s)}
                      aria-pressed={s.key === activeId}
                      className={`w-full min-h-[56px] px-4 rounded-btn border flex items-center gap-3 text-base ${
                        s.key === activeId
                          ? 'border-hairline-strong bg-primary-soft text-primary font-bold'
                          : 'border-hairline text-ink'
                      }`}
                    >
                      <span aria-hidden className="flex h-8 w-8 shrink-0 items-center justify-center rounded-pill bg-primary-soft text-primary">
                        {s.user.role === 'family' ? (
                          <Users className="h-4 w-4" />
                        ) : (
                          <UserRound className="h-4 w-4" />
                        )}
                      </span>
                      <span className="truncate">{s.user.name || s.user.username}</span>
                      {s.key === activeId && <Check aria-hidden className="ml-auto h-5 w-5" />}
                    </button>
                  ))}
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    <Link
                      href="/login"
                      className="min-h-[52px] px-4 rounded-btn bg-primary-soft text-primary font-bold flex items-center justify-center gap-1"
                    >
                      <Plus aria-hidden className="h-4 w-4" />
                      添加账号
                    </Link>
                    <button
                      type="button"
                      onClick={handleLogout}
                      className="min-h-[52px] px-4 rounded-btn bg-danger-soft text-danger font-bold"
                    >
                      退出登录
                    </button>
                  </div>
                </div>
              ) : (
                <Link
                  href="/login"
                  className="min-h-[56px] px-4 rounded-btn bg-primary text-on-primary font-bold shadow-btn flex items-center justify-center"
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

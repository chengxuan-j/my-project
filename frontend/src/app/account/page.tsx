'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AtSign, ShieldCheck, UserRound } from 'lucide-react';
import { ApiError, authApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { PageHeader } from '@/components/ui/PageHeader';
import { SectionCard } from '@/components/ui/SectionCard';
import { Badge } from '@/components/ui/Badge';

export default function AccountPage() {
  const router = useRouter();
  const { user, accessToken, updateUserName, updateLoginName } = useAuthStore();
  const [authReady, setAuthReady] = useState(false);
  const [currentEmail, setCurrentEmail] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [savingAccount, setSavingAccount] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const persist = useAuthStore.persist;
    if (persist.hasHydrated()) setAuthReady(true);
    else return persist.onFinishHydration(() => setAuthReady(true));
  }, []);

  // 先用本地缓存兜底，等 /auth/me 回来再用服务端名字覆盖
  useEffect(() => {
    if (!authReady || !user) return;
    setName((prev) => prev || user.name || '');
    setUsername((prev) => prev || user.username || '');
  }, [authReady, user]);

  useEffect(() => {
    if (!authReady) return;
    if (!accessToken) {
      router.replace('/login');
      return;
    }
    authApi.me().then((me) => {
      setCurrentEmail(me.email || '');
      setEmail(me.email || '');
      setUsername(me.username);
      if (me.username) updateLoginName(me.username);
      // 服务端名字优先：本地缓存可能是旧版本登录时留下的
      if (me.name) {
        setName(me.name);
        updateUserName(me.name);
      }
    }).catch((err) => setError(err instanceof ApiError ? err.message : '账号信息加载失败'));
  }, [authReady, accessToken, router]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  const sendCode = async () => {
    setError('');
    setNotice('');
    if (!email.trim() || !email.includes('@')) {
      setError('请输入正确的邮箱地址');
      return;
    }
    if (email.trim().toLowerCase() === currentEmail.toLowerCase()) {
      setNotice('当前账号已经绑定该邮箱');
      return;
    }
    setSending(true);
    try {
      const result = await authApi.sendEmailCode(email.trim(), 'bind');
      setCooldown(result.retry_after || 60);
      setNotice(result.message);
      if (result.debug_code) {
        setCode(result.debug_code);
        setNotice(`${result.message}：${result.debug_code}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '验证码发送失败');
    } finally {
      setSending(false);
    }
  };

  const bindEmail = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    if (!email.trim() || !/^\d{6}$/.test(code)) {
      setError('请输入邮箱和 6 位验证码');
      return;
    }
    setSaving(true);
    try {
      const result = await authApi.bindEmail(email.trim(), code);
      setCurrentEmail(result.email);
      setCode('');
      setNotice('邮箱绑定成功，现在可以使用验证码登录');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '邮箱绑定失败');
    } finally {
      setSaving(false);
    }
  };

  const saveAccount = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');

    const nextUsername = username.trim();
    const nextName = name.trim();
    const usernameChanged = nextUsername !== user!.username;
    const nameChanged = user!.role === 'elderly' && nextName !== (user!.name || '');

    if (!nextUsername) {
      setError('登录用户名不能为空');
      return;
    }
    if (nextUsername.length < 3 || nextUsername.length > 64) {
      setError('登录用户名需要 3~64 个字符');
      return;
    }
    if (!/^[A-Za-z0-9_\-\u4e00-\u9fff]+$/.test(nextUsername)) {
      setError('登录用户名只能用中文、字母、数字、下划线或短横线，不能有空格');
      return;
    }
    if (nameChanged && !nextName) {
      setError('称呼不能为空');
      return;
    }
    if (usernameChanged && !password) {
      setError('修改登录用户名需要输入当前密码');
      return;
    }
    if (!usernameChanged && !nameChanged) {
      setNotice('没有需要保存的改动');
      return;
    }

    setSavingAccount(true);
    try {
      if (usernameChanged) {
        const result = await authApi.updateUsername(nextUsername, password);
        updateLoginName(result.username);
        setUsername(result.username);
        setPassword('');
      }
      if (nameChanged) {
        const result = await authApi.updateName(nextName);
        setName(result.name);
        updateUserName(result.name);
      }
      setNotice(
        usernameChanged
          ? '登录用户名已改，下次请用新用户名登录（旧用户名立即失效）'
          : '称呼已更新，导航栏和聊天里都会用新称呼'
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败');
    } finally {
      setSavingAccount(false);
    }
  };

  if (!authReady || !accessToken || !user) {
    return <div className="min-h-[50vh] flex items-center justify-center text-muted">正在加载账号…</div>;
  }

  const pendingUsernameChange = !!username && username.trim() !== user.username;

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <PageHeader
        eyebrow="账号安全"
        title="邮箱与登录"
        description="管理登录用户名、称呼和邮箱绑定，保护您的账号。"
        icon={<ShieldCheck aria-hidden className="h-7 w-7 text-primary" />}
      />

      {error && <div className="rounded-btn bg-danger-soft px-4 py-3 text-danger">{error}</div>}
      {notice && <div className="rounded-btn bg-success-soft px-4 py-3 text-success">{notice}</div>}

      <div className="grid lg:grid-cols-2 gap-5 items-start">
      <SectionCard
        title="我的账号"
        icon={<UserRound aria-hidden className="h-5 w-5" />}
        meta={user.role === 'elderly' ? '老人账号' : '家属账号'}
      >
        <p className="text-sm text-muted">
          登录用户名用来登录；{user.role === 'elderly' ? '称呼是 AI 和家里人叫你的名字，两者可以不一样。' : '称呼仅老人账号可设置。'}
        </p>
        <form onSubmit={saveAccount} className="mt-4 space-y-4">
          <label htmlFor="login-username" className="block">
            <span className="block mb-2 font-medium text-ink">登录用户名</span>
            <input
              id="login-username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              maxLength={64}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg bg-card"
              placeholder="用于登录的用户名"
              autoComplete="username"
            />
            <span className="block mt-1 text-sm text-muted">
              3~64 个字符，可用中文、字母、数字、下划线、短横线
            </span>
          </label>

          {user.role === 'elderly' && (
            <label htmlFor="display-name" className="block">
              <span className="block mb-2 font-medium text-ink">称呼</span>
              <input
                id="display-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={20}
                className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg bg-card"
                placeholder="比如：李奶奶"
                autoComplete="nickname"
              />
              <span className="block mt-1 text-sm text-muted">最多 20 个字</span>
            </label>
          )}

          {pendingUsernameChange && (
            <>
              <label htmlFor="current-password" className="block">
                <span className="block mb-2 font-medium text-ink">
                  当前密码（确认是本人操作）
                </span>
                <input
                  id="current-password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg bg-card"
                  placeholder="输入当前登录密码"
                  autoComplete="current-password"
                />
              </label>
              <p className="text-sm text-warning">
                改完后旧用户名立即失效，下次请用新用户名登录；已绑定的家属关系不受影响。
              </p>
            </>
          )}

          <button
            type="submit"
            disabled={savingAccount}
            className="w-full min-h-[56px] rounded-btn bg-primary text-on-primary shadow-btn font-bold hover:bg-primary-strong disabled:opacity-50"
          >
            {savingAccount ? '保存中…' : '保存修改'}
          </button>
        </form>
      </SectionCard>

      <SectionCard
        title="邮箱绑定"
        icon={<AtSign aria-hidden className="h-5 w-5" />}
        meta={currentEmail || '用于验证码登录'}
        actions={
          <Badge tone={currentEmail ? 'success' : 'warning'}>
            {currentEmail ? '已绑定' : '未绑定'}
          </Badge>
        }
      >
        <div className="flex items-center justify-between gap-4 flex-wrap pb-4 border-b border-hairline">
          <div>
            <p className="text-sm text-muted">当前账号</p>
            <p className="font-bold text-ink mt-1">{user.name || user.username}</p>
          </div>
          <p className="text-sm text-muted">{currentEmail || '还没有绑定邮箱'}</p>
        </div>

        <form onSubmit={bindEmail} className="space-y-5 mt-4">
          <div>
            <label htmlFor="account-email" className="block mb-2 font-medium text-ink">邮箱</label>
            <input id="account-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none bg-card" placeholder="name@example.com" autoComplete="email" />
          </div>
          <div>
            <label htmlFor="account-email-code" className="block mb-2 font-medium text-ink">验证码</label>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input id="account-email-code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className="min-w-0 min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none tracking-widest bg-card" placeholder="6 位验证码" autoComplete="one-time-code" />
              <button type="button" onClick={sendCode} disabled={sending || cooldown > 0} className="min-w-[120px] min-h-[56px] px-4 rounded-btn border border-primary text-primary font-semibold hover:bg-primary-soft disabled:opacity-50">{sending ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}</button>
            </div>
          </div>

          <p className="text-sm text-muted">
            绑定邮箱后，可以用「邮箱验证码」方式登录，忘记密码时也更容易找回。
          </p>

          <button disabled={saving} className="w-full min-h-[56px] rounded-btn bg-primary hover:bg-primary-strong text-on-primary shadow-btn font-bold disabled:opacity-50">{saving ? '保存中…' : currentEmail ? '更换绑定邮箱' : '绑定邮箱'}</button>
        </form>
      </SectionCard>
      </div>
    </div>
  );
}

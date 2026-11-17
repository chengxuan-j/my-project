'use client';

import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { authApi, ApiError } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { LargeButton } from '@/components/LargeButton';
import { Flower2, PartyPopper, ShieldCheck, User, Users } from 'lucide-react';

type Role = 'elderly' | 'family';

export default function RegisterPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [role, setRole] = useState<Role>('elderly');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [email, setEmail] = useState('');
  const [emailCode, setEmailCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [notice, setNotice] = useState('');
  const [name, setName] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [successInfo, setSuccessInfo] = useState('');

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(
      () => setCooldown((seconds) => Math.max(0, seconds - 1)),
      1000
    );
    return () => window.clearInterval(timer);
  }, [cooldown]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!username.trim() || !password) {
      setError('请输入用户名和密码');
      return;
    }
    if (email.trim() && !/^\d{6}$/.test(emailCode)) {
      setError('填写邮箱后，需要先获取并输入 6 位验证码');
      return;
    }
    setLoading(true);
    try {
      const res = await authApi.register({
        username: username.trim(),
        password,
        email: email.trim() || undefined,
        email_code: email.trim() ? emailCode : undefined,
        role,
        name: name.trim() || undefined,
        invite_code: role === 'family' && inviteCode.trim() ? inviteCode.trim() : undefined,
      });
      setAuth(
        {
          user_id: res.user_id,
          username: res.username,
          role: res.role,
          elderly_id: res.elderly_id,
          name: res.name,
        },
        res.access_token,
        res.refresh_token
      );
      // 老人注册成功：先显示邀请码，让老人抄给家属
      if (res.role === 'elderly' && res.invite_code) {
        setSuccessInfo(res.invite_code);
      } else {
        router.push(res.role === 'family' ? '/family' : '/');
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '注册失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleSendEmailCode = async () => {
    setError('');
    setNotice('');
    if (!email.trim() || !email.includes('@')) {
      setError('请输入正确的邮箱地址');
      return;
    }
    setSendingCode(true);
    try {
      const res = await authApi.sendEmailCode(email.trim(), 'register');
      setCooldown(res.retry_after || 60);
      setNotice(res.message);
      if (res.debug_code) {
        setEmailCode(res.debug_code);
        setNotice(`${res.message}：${res.debug_code}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '验证码发送失败');
    } finally {
      setSendingCode(false);
    }
  };

  // 注册成功且是老人：显示邀请码
  if (successInfo) {
    return (
      <div className="app-min-screen flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md bg-card rounded-card shadow-card p-8 border border-hairline text-center space-y-6">
          <div className="flex justify-center">
            <PartyPopper aria-hidden className="h-16 w-16 text-warning" />
          </div>
          <h1 className="text-2xl font-bold text-primary">注册成功！</h1>
          <div className="bg-butter rounded-card p-6">
            <p className="text-ink mb-3">您的专属邀请码（请告诉家人）：</p>
            <p className="text-4xl font-mono font-bold text-primary tracking-widest">
              {successInfo}
            </p>
            <p className="text-sm text-muted mt-3">
              家属用您的用户名 <b>{username}</b> + 这个邀请码，就能绑定查看您的状态
            </p>
          </div>
          <LargeButton onClick={() => router.push('/')} size="xl" className="w-full">
            开始使用 →
          </LargeButton>
        </div>
      </div>
    );
  }

  return (
    <div className="app-min-screen grid lg:grid-cols-[1.05fr_1fr]">
      {/* ---------- 桌面品牌区 ---------- */}
      <aside className="relative hidden lg:flex flex-col justify-between overflow-hidden bg-primary p-12 text-on-primary">
        <div
          aria-hidden
          className="absolute -top-24 -right-24 h-72 w-72 rounded-pill bg-white/10"
        />
        <div
          aria-hidden
          className="absolute bottom-16 -left-16 h-56 w-56 rounded-pill bg-white/10"
        />
        <div className="relative flex items-center gap-2.5 text-xl font-bold">
          <Flower2 aria-hidden className="h-7 w-7" />
          陪伴 AI
        </div>
        <div className="relative">
          <h2 className="font-display text-4xl font-bold leading-snug">
            一分钟注册，
            <br />
            让陪伴从今天开始
          </h2>
          <ul className="mt-8 space-y-4 text-base/relaxed text-on-primary/85">
            <li className="flex items-center gap-3">
              <User aria-hidden className="h-5 w-5 shrink-0" />
              老人端：大字、语音、方言，怎么方便怎么来
            </li>
            <li className="flex items-center gap-3">
              <Users aria-hidden className="h-5 w-5 shrink-0" />
              家属端：用邀请码绑定，远程关注状态
            </li>
            <li className="flex items-center gap-3">
              <ShieldCheck aria-hidden className="h-5 w-5 shrink-0" />
              聊天内容只用于陪伴，不做其他用途
            </li>
          </ul>
        </div>
        <p className="relative text-sm text-on-primary/60">老人情感陪伴 AI · Demo</p>
      </aside>

      {/* ---------- 表单区 ---------- */}
      <main className="flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center justify-center gap-2 text-primary lg:hidden">
            <Flower2 aria-hidden className="h-7 w-7" />
            <span className="text-xl font-bold">陪伴 AI</span>
          </div>

          <h1 className="text-3xl font-bold text-ink mb-1.5">注册账号</h1>
          <p className="text-muted mb-6">选择您的身份</p>

        {/* 角色选择 */}
        <div className="grid grid-cols-2 gap-3 mb-6">
          <button
            type="button"
            onClick={() => setRole('elderly')}
            aria-pressed={role === 'elderly'}
            className={`inline-flex min-h-[80px] items-center justify-center gap-2 rounded-card border font-bold text-xl transition-colors ${
              role === 'elderly'
                ? 'bg-primary text-on-primary border-primary'
                : 'bg-card text-ink border-hairline hover:border-primary'
            }`}
          >
            <User aria-hidden className="h-6 w-6" />
            我是老人
          </button>
          <button
            type="button"
            onClick={() => setRole('family')}
            aria-pressed={role === 'family'}
            className={`inline-flex min-h-[80px] items-center justify-center gap-2 rounded-card border font-bold text-xl transition-colors ${
              role === 'family'
                ? 'bg-primary text-on-primary border-primary'
                : 'bg-card text-ink border-hairline hover:border-primary'
            }`}
          >
            <Users aria-hidden className="h-6 w-6" />
            我是家属
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="reg-username" className="block mb-2 font-medium text-ink">
              用户名 <span className="text-danger">*</span>
            </label>
            <input
              id="reg-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none"
              autoComplete="username"
            />
          </div>
          <div>
            <label htmlFor="reg-password" className="block mb-2 font-medium text-ink">
              密码 <span className="text-danger">*</span>
            </label>
            <input
              id="reg-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none"
              autoComplete="new-password"
            />
          </div>
          <div>
            <label htmlFor="reg-email" className="block mb-2 font-medium text-ink">
              邮箱（可选，用于验证码登录）
            </label>
            <input
              id="reg-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none"
              placeholder="name@example.com"
              autoComplete="email"
            />
            {email.trim() && (
              <div className="grid grid-cols-[1fr_auto] gap-2 mt-2">
                <input
                  id="reg-email-code"
                  type="text"
                  inputMode="numeric"
                  value={emailCode}
                  onChange={(e) => setEmailCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                  className="min-w-0 min-h-[52px] px-4 rounded-input border border-hairline focus:border-primary outline-none tracking-widest"
                  placeholder="6 位邮箱验证码"
                  autoComplete="one-time-code"
                />
                <button
                  type="button"
                  onClick={handleSendEmailCode}
                  disabled={sendingCode || cooldown > 0}
                  className="min-w-[120px] min-h-[52px] px-4 rounded-btn border border-primary text-primary font-semibold hover:bg-primary-soft disabled:opacity-50"
                >
                  {sendingCode ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}
                </button>
              </div>
            )}
          </div>
          <div>
            <label htmlFor="reg-name" className="block mb-2 font-medium text-ink">
              称呼（如：王奶奶）
            </label>
            <input
              id="reg-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none"
            />
          </div>
          {role === 'family' && (
            <div>
              <label htmlFor="reg-invite" className="block mb-2 font-medium text-ink">
                老人邀请码（可选，注册后再绑定也行）
              </label>
              <input
                id="reg-invite"
                type="text"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none"
              />
            </div>
          )}

          {error && (
            <div className="bg-danger-soft text-danger rounded-btn px-4 py-3">
              {error}
            </div>
          )}
          {notice && (
            <div className="bg-success-soft text-success rounded-btn px-4 py-3">
              {notice}
            </div>
          )}

          <LargeButton type="submit" size="xl" disabled={loading} className="w-full">
            {loading ? '注册中...' : '注 册'}
          </LargeButton>
        </form>

        <p className="text-center mt-6 text-muted">
          已有账号？{' '}
          <Link href="/login" className="text-primary font-bold underline">
            去登录
          </Link>
        </p>
        </div>
      </main>
    </div>
  );
}

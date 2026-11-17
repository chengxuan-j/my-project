'use client';

import { FormEvent, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { authApi, ApiError } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { LargeButton } from '@/components/LargeButton';
import { Eye, EyeOff, Flower2, MessageCircle, Mic, ShieldCheck } from 'lucide-react';

export default function LoginPage() {
  const router = useRouter();
  const setAuth = useAuthStore((s) => s.setAuth);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [mode, setMode] = useState<'password' | 'email'>('password');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [sendingCode, setSendingCode] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  const completeLogin = (res: Awaited<ReturnType<typeof authApi.login>>) => {
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
    router.push(res.role === 'family' ? '/family' : '/');
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    if (mode === 'password' && (!username.trim() || !password)) {
      setError('请输入用户名和密码');
      return;
    }
    if (mode === 'email' && (!email.trim() || !/^\d{6}$/.test(code))) {
      setError('请输入邮箱和 6 位验证码');
      return;
    }
    setLoading(true);
    try {
      const res = mode === 'password'
        ? await authApi.login(username.trim(), password)
        : await authApi.emailLogin(email.trim(), code);
      completeLogin(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '登录失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  const handleSendCode = async () => {
    setError('');
    setNotice('');
    if (!email.trim() || !email.includes('@')) {
      setError('请输入正确的邮箱地址');
      return;
    }
    setSendingCode(true);
    try {
      const res = await authApi.sendEmailCode(email.trim());
      setCooldown(res.retry_after || 60);
      setNotice(res.message);
      if (res.debug_code) {
        setCode(res.debug_code);
        setNotice(`${res.message}：${res.debug_code}`);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '验证码发送失败');
    } finally {
      setSendingCode(false);
    }
  };

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
            温暖的陪伴，
            <br />
            随时光与记忆同行
          </h2>
          <ul className="mt-8 space-y-4 text-base/relaxed text-on-primary/85">
            <li className="flex items-center gap-3">
              <MessageCircle aria-hidden className="h-5 w-5 shrink-0" />
              听得懂情绪的聊天陪伴，越聊越懂你
            </li>
            <li className="flex items-center gap-3">
              <Mic aria-hidden className="h-5 w-5 shrink-0" />
              按住说话就行，方言也能聊
            </li>
            <li className="flex items-center gap-3">
              <ShieldCheck aria-hidden className="h-5 w-5 shrink-0" />
              家人可远程关注，安心又放心
            </li>
          </ul>
        </div>

        <p className="relative text-sm text-on-primary/60">老人情感陪伴 AI · Demo</p>
      </aside>

      {/* ---------- 表单区 ---------- */}
      <main className="flex items-center justify-center px-4 py-8">
        <div className="w-full max-w-md">
          {/* 手机端品牌头 */}
          <div className="mb-6 flex items-center justify-center gap-2 text-primary lg:hidden">
            <Flower2 aria-hidden className="h-7 w-7" />
            <span className="text-xl font-bold">陪伴 AI</span>
          </div>

          <h1 className="text-3xl font-bold text-ink mb-1.5">欢迎回来</h1>
          <p className="text-muted mb-6">登录老人情感陪伴 AI</p>

          <div className="grid grid-cols-2 bg-primary-soft rounded-btn p-1 mb-6" role="tablist" aria-label="登录方式">
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'password'}
              onClick={() => { setMode('password'); setError(''); setNotice(''); }}
              className={`min-h-[48px] rounded-btn font-semibold ${mode === 'password' ? 'bg-card text-primary shadow-card' : 'text-muted'}`}
            >
              密码登录
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={mode === 'email'}
              onClick={() => { setMode('email'); setError(''); setNotice(''); }}
              className={`min-h-[48px] rounded-btn font-semibold ${mode === 'email' ? 'bg-card text-primary shadow-card' : 'text-muted'}`}
            >
              邮箱验证码
            </button>
          </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {mode === 'password' ? <><div>
            <label htmlFor="username" className="block mb-2 font-medium text-ink">
              用户名
            </label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg"
              placeholder="请输入用户名"
              autoComplete="username"
            />
          </div>
          <div>
            <label htmlFor="password" className="block mb-2 font-medium text-ink">
              密码
            </label>
            <div className="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full min-h-[56px] pl-4 pr-16 rounded-input border border-hairline focus:border-primary outline-none text-lg"
                placeholder="请输入密码"
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? '隐藏密码' : '显示密码'}
                aria-pressed={showPassword}
                title={showPassword ? '隐藏密码' : '显示密码'}
                className="absolute right-2 top-1/2 -translate-y-1/2 w-12 h-12 flex items-center justify-center rounded-btn text-muted hover:bg-primary-soft focus:outline-none focus:ring-2 focus:ring-[color:var(--ring)]"
              >
                {showPassword ? <EyeOff aria-hidden className="h-6 w-6" /> : <Eye aria-hidden className="h-6 w-6" />}
              </button>
            </div>
          </div></> : <>
          <div>
            <label htmlFor="login-email" className="block mb-2 font-medium text-ink">
              邮箱
            </label>
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg"
              placeholder="name@example.com"
              autoComplete="email"
            />
          </div>
          <div>
            <label htmlFor="email-code" className="block mb-2 font-medium text-ink">
              验证码
            </label>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input
                id="email-code"
                type="text"
                inputMode="numeric"
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className="min-w-0 min-h-[56px] px-4 rounded-input border border-hairline focus:border-primary outline-none text-lg tracking-widest"
                placeholder="6 位验证码"
                autoComplete="one-time-code"
              />
              <button
                type="button"
                onClick={handleSendCode}
                disabled={sendingCode || cooldown > 0}
                className="min-w-[120px] min-h-[56px] px-4 rounded-btn border border-primary text-primary font-semibold hover:bg-primary-soft disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {sendingCode ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}
              </button>
            </div>
          </div>
          </>}

          {notice && (
            <div className="bg-success-soft text-success rounded-btn px-4 py-3">
              {notice}
            </div>
          )}

          {error && (
            <div className="bg-danger-soft text-danger rounded-btn px-4 py-3">
              {error}
            </div>
          )}

          <LargeButton type="submit" size="xl" disabled={loading} className="w-full">
            {loading ? '登录中...' : mode === 'password' ? '登 录' : '验证码登录'}
          </LargeButton>
        </form>

        <p className="text-center mt-6 text-muted">
          还没有账号？{' '}
          <Link href="/register" className="text-primary font-bold underline">
            立即注册
          </Link>
        </p>
        </div>
      </main>
    </div>
  );
}

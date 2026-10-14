'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, authApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

export default function AccountPage() {
  const router = useRouter();
  const { user, accessToken } = useAuthStore();
  const [authReady, setAuthReady] = useState(false);
  const [currentEmail, setCurrentEmail] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const [sending, setSending] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    const persist = useAuthStore.persist;
    if (persist.hasHydrated()) setAuthReady(true);
    else return persist.onFinishHydration(() => setAuthReady(true));
  }, []);

  useEffect(() => {
    if (!authReady) return;
    if (!accessToken) {
      router.replace('/login');
      return;
    }
    authApi.me().then((me) => {
      setCurrentEmail(me.email || '');
      setEmail(me.email || '');
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

  if (!authReady || !accessToken || !user) {
    return <div className="min-h-[50vh] flex items-center justify-center text-gray-500">正在加载账号…</div>;
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
      <header>
        <p className="text-sm font-semibold text-amber-600">账号安全</p>
        <h1 className="text-3xl font-bold text-gray-900 mt-1">邮箱与登录</h1>
      </header>

      <section className="bg-white rounded-2xl border border-slate-200 p-6 shadow-sm">
        <div className="flex items-center justify-between gap-4 flex-wrap pb-5 border-b border-slate-100">
          <div><p className="text-sm text-gray-500">当前账号</p><p className="font-bold text-gray-900 mt-1">{user.name || user.username}</p></div>
          <span className={`px-3 py-1 rounded-full text-sm font-semibold ${currentEmail ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>{currentEmail ? '邮箱已绑定' : '尚未绑定邮箱'}</span>
        </div>

        <form onSubmit={bindEmail} className="space-y-5 mt-5">
          <div>
            <label htmlFor="account-email" className="block mb-2 font-medium text-gray-700">邮箱</label>
            <input id="account-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full min-h-[56px] px-4 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none" placeholder="name@example.com" autoComplete="email" />
          </div>
          <div>
            <label htmlFor="account-email-code" className="block mb-2 font-medium text-gray-700">验证码</label>
            <div className="grid grid-cols-[1fr_auto] gap-2">
              <input id="account-email-code" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} className="min-w-0 min-h-[56px] px-4 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none tracking-widest" placeholder="6 位验证码" autoComplete="one-time-code" />
              <button type="button" onClick={sendCode} disabled={sending || cooldown > 0} className="min-w-[120px] min-h-[56px] px-4 rounded-xl border-2 border-warm-primary text-warm-primary font-semibold hover:bg-warm-light disabled:opacity-50">{sending ? '发送中…' : cooldown > 0 ? `${cooldown} 秒` : '获取验证码'}</button>
            </div>
          </div>

          {error && <div className="rounded-xl border-2 border-red-200 bg-red-50 px-4 py-3 text-red-700">{error}</div>}
          {notice && <div className="rounded-xl border-2 border-emerald-200 bg-emerald-50 px-4 py-3 text-emerald-700">{notice}</div>}

          <button disabled={saving} className="w-full min-h-[56px] rounded-xl bg-warm-primary hover:bg-warm-dark text-white font-bold disabled:opacity-50">{saving ? '保存中…' : currentEmail ? '更换绑定邮箱' : '绑定邮箱'}</button>
        </form>
      </section>
    </div>
  );
}

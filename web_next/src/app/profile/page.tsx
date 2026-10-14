'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { profileApi, memoryApi, ApiError, Profile, MemoryItem } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { LargeButton } from '@/components/LargeButton';
import { MoodCalendar } from '@/components/MoodCalendar';
import { MemoryList } from '@/components/MemoryList';

export default function ProfilePage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const [profile, setProfile] = useState<Profile>({});
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !accessToken) {
      router.push('/login');
      return;
    }
    // 家属不能访问老人画像页
    if (hydrated && accessToken && user?.role === 'family') {
      router.push('/family');
    }
  }, [hydrated, accessToken, user, router]);

  useEffect(() => {
    if (!hydrated || !accessToken) return;
    Promise.all([
      profileApi.get().catch(() => ({})),
      memoryApi.list().catch(() => ({ memories: [] })),
    ])
      .then(([p, m]) => {
        setProfile(p || {});
        setMemories(m.memories || []);
      })
      .finally(() => setLoading(false));
  }, [hydrated, accessToken]);

  if (!hydrated || !accessToken) return null;

  const updateField = (key: string, value: unknown) => {
    setProfile((p) => ({ ...p, [key]: value }));
  };

  const handleSave = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setMessage('');
    setError('');
    try {
      const updated = await profileApi.update(profile);
      setProfile(updated);
      setMessage('✅ 保存成功！');
      setTimeout(() => setMessage(''), 3000);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteMemory = async (id: number) => {
    if (!confirm('确定要删除这条记忆吗？')) return;
    try {
      await memoryApi.remove(id);
      setMemories((m) => m.filter((x) => x.id !== id));
    } catch (err) {
      alert(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  const refreshMemories = async () => {
    try {
      const m = await memoryApi.list();
      setMemories(m.memories || []);
    } catch {
      // 静默失败
    }
  };

  const interestsStr = Array.isArray(profile.interests)
    ? profile.interests.join('、')
    : (profile.interests as string) || '';

  const interestChips = Array.isArray(profile.interests)
    ? (profile.interests as string[]).filter(Boolean)
    : typeof profile.interests === 'string'
      ? (profile.interests as string).split(/[、,，;；\s]+/).filter(Boolean)
      : [];

  const healthChips =
    typeof profile.health === 'string'
      ? (profile.health as string)
          .split(/[、,，;；\n]+/)
          .map((s) => s.trim())
          .filter(Boolean)
      : [];

  const genderLabel =
    profile.gender === 'male'
      ? '♂ 男'
      : profile.gender === 'female'
        ? '♀ 女'
        : profile.gender === 'other'
          ? '⚧ 其他'
          : '';

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 text-center text-gray-600">
        加载中...
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      <h1 className="text-2xl font-bold text-warm-primary">👤 我的画像</h1>

      {/* 我的档案（只读速览，chips 展示） */}
      <section className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-2xl shadow-sm border-2 border-amber-200 p-6">
        <h2 className="text-lg font-bold text-gray-900 mb-3">📇 我的档案</h2>

        <div className="flex flex-wrap gap-2 mb-4">
          {(profile.name as string) && (
            <span className="px-3 py-1 rounded-lg bg-white text-gray-800 font-medium">
              👤 {profile.name as string}
            </span>
          )}
          {(profile.age as number) != null && (
            <span className="px-3 py-1 rounded-lg bg-white text-gray-800 font-medium">
              🎂 {profile.age as number} 岁
            </span>
          )}
          {genderLabel && (
            <span className="px-3 py-1 rounded-lg bg-white text-gray-800 font-medium">
              {genderLabel}
            </span>
          )}
        </div>

        <p className="text-sm font-medium text-gray-600 mb-1">兴趣爱好</p>
        <div className="flex flex-wrap gap-2 mb-4">
          {interestChips.length === 0 ? (
            <span className="text-gray-500 text-sm">还没填写，下面补上吧</span>
          ) : (
            interestChips.map((it) => (
              <span
                key={it}
                className="px-3 py-1 rounded-full bg-warm-primary text-white text-sm"
              >
                🎯 {it}
              </span>
            ))
          )}
        </div>

        <p className="text-sm font-medium text-gray-600 mb-1">健康情况</p>
        <div className="flex flex-wrap gap-2">
          {healthChips.length === 0 ? (
            <span className="text-gray-500 text-sm">还没填写</span>
          ) : (
            healthChips.map((h) => (
              <span
                key={h}
                className="px-3 py-1 rounded-full bg-white border border-warm-primary text-warm-primary text-sm"
              >
                💊 {h}
              </span>
            ))
          )}
        </div>
      </section>

      <form
        onSubmit={handleSave}
        className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6 space-y-4"
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label htmlFor="p-name" className="block mb-1 font-medium text-gray-700">
              姓名/称呼
            </label>
            <input
              id="p-name"
              type="text"
              value={(profile.name as string) || ''}
              onChange={(e) => updateField('name', e.target.value)}
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
            />
          </div>
          <div>
            <label htmlFor="p-age" className="block mb-1 font-medium text-gray-700">
              年龄
            </label>
            <input
              id="p-age"
              type="number"
              min={0}
              max={150}
              value={(profile.age as number) ?? ''}
              onChange={(e) =>
                updateField('age', e.target.value ? Number(e.target.value) : undefined)
              }
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
            />
          </div>
          <div>
            <label htmlFor="p-gender" className="block mb-1 font-medium text-gray-700">
              性别
            </label>
            <select
              id="p-gender"
              value={(profile.gender as string) || ''}
              onChange={(e) => updateField('gender', e.target.value)}
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none bg-white"
            >
              <option value="">请选择</option>
              <option value="male">男</option>
              <option value="female">女</option>
              <option value="other">其他</option>
            </select>
          </div>
          <div>
            <label htmlFor="p-interests" className="block mb-1 font-medium text-gray-700">
              兴趣爱好（顿号分隔）
            </label>
            <input
              id="p-interests"
              type="text"
              value={interestsStr}
              onChange={(e) =>
                updateField(
                  'interests',
                  e.target.value.split(/[、,，]/).filter(Boolean)
                )
              }
              placeholder="如：下棋、唱戏、养花"
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
            />
          </div>
        </div>
        <div>
          <label htmlFor="p-health" className="block mb-1 font-medium text-gray-700">
            健康情况
          </label>
          <textarea
            id="p-health"
            rows={3}
            value={(profile.health as string) || ''}
            onChange={(e) => updateField('health', e.target.value)}
            placeholder="如：有高血压，腿脚不太方便..."
            className="w-full px-3 py-2 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none resize-none"
          />
        </div>

        {message && (
          <div className="bg-green-50 border-2 border-green-300 text-green-700 rounded-xl px-4 py-2">
            {message}
          </div>
        )}
        {error && (
          <div className="bg-red-50 border-2 border-red-300 text-red-700 rounded-xl px-4 py-2">
            {error}
          </div>
        )}

        <LargeButton type="submit" size="lg" disabled={saving} className="w-full md:w-auto">
          {saving ? '保存中...' : '💾 保存画像'}
        </LargeButton>
      </form>

      {/* 我的心情日历 */}
      <MoodCalendar />

      {/* 邀请码（仅老人） */}
      <InviteCodeCard />

      {/* 长期记忆 */}
      <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-gray-900">🧠 AI 记住的事（{memories.length}）</h2>
          <button
            type="button"
            onClick={refreshMemories}
            className="min-h-[40px] px-4 rounded-xl bg-warm-light hover:bg-warm-primary hover:text-white text-gray-700 transition-colors"
            title="聊天后 AI 会在后台整理记忆，点这里刷新"
          >
            🔄 刷新
          </button>
        </div>
        <p className="text-sm text-gray-500 mb-4 bg-blue-50 border border-blue-200 rounded-xl px-3 py-2">
          💡 上面是您主动填的"画像"，AI 每次聊天都会参考。这里是聊天中 AI <b>自动记下</b>的关键事，比如"女儿叫小芳"、"喜欢邓丽君"。聊天后等几秒点刷新能看到新记忆。
        </p>
        <MemoryList memories={memories} onDelete={handleDeleteMemory} />
      </section>
    </div>
  );
}

/** 邀请码卡片：仅老人角色显示，家属绑定用 */
function InviteCodeCard() {
  const user = useAuthStore((s) => s.user);
  const accessToken = useAuthStore((s) => s.accessToken);
  const [code, setCode] = useState('');
  const [show, setShow] = useState(false);

  useEffect(() => {
    if (!accessToken || user?.role !== 'elderly') return;
    // 拉取邀请码
    fetch('/api/v1/auth/invite-code', {
      headers: { Authorization: `Bearer ${accessToken}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.invite_code && setCode(d.invite_code))
      .catch(() => {});
  }, [accessToken, user?.role]);

  if (user?.role !== 'elderly' || !code) return null;

  return (
    <section className="bg-gradient-to-r from-amber-50 to-orange-50 rounded-2xl shadow-sm border-2 border-amber-200 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold text-gray-900 mb-1">🔑 我的邀请码</h2>
          <p className="text-sm text-gray-600">把这个码告诉家人，他们就能绑定查看您的状态</p>
        </div>
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="min-h-[48px] px-6 rounded-xl bg-warm-primary text-white font-bold"
        >
          {show ? '隐藏' : '显示'}
        </button>
      </div>
      {show && (
        <div className="mt-4 bg-white rounded-xl px-6 py-4 text-center">
          <p className="text-4xl font-mono font-bold text-warm-primary tracking-widest">
            {code}
          </p>
        </div>
      )}
    </section>
  );
}

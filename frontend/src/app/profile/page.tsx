'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Brain, Cake, KeyRound, Pill, RefreshCw, Save, Target, UserRound } from 'lucide-react';
import { profileApi, memoryApi, ApiError, Profile, MemoryItem } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { LargeButton } from '@/components/LargeButton';
import { MoodCalendar } from '@/components/MoodCalendar';
import { MemoryList } from '@/components/MemoryList';
import { PageHeader } from '@/components/ui/PageHeader';
import { SectionCard } from '@/components/ui/SectionCard';
import { Badge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';

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
      // 名字可能改了：同步到全局会话，导航栏/聊天头部立即生效
      if (typeof updated.name === 'string' && updated.name.trim()) {
        useAuthStore.getState().updateUserName(updated.name.trim());
      }
      setMessage('保存成功');
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
      ? '男'
      : profile.gender === 'female'
        ? '女'
        : profile.gender === 'other'
          ? '其他'
          : '';

  const displayName = (profile.name as string) || user?.name || user?.username || '您';

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8 text-center text-muted">
        加载中...
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <PageHeader
        eyebrow="AI 眼中的你"
        title="我的画像"
        description="您填写的资料和聊天里自然聊到的事，都会让陪伴更懂您。"
        icon={<UserRound aria-hidden className="h-7 w-7 text-primary" />}
      />

      <div className="grid lg:grid-cols-[360px_1fr] gap-5 items-start">
        {/* 左栏：档案速览 + 邀请码 + 心情日历 */}
        <div className="space-y-5">
          <SectionCard title="我的档案" icon={<UserRound aria-hidden className="h-5 w-5" />}>
            <div className="flex items-center gap-3 mb-4">
              <span
                aria-hidden
                className="flex h-12 w-12 shrink-0 items-center justify-center rounded-pill bg-primary text-on-primary text-xl font-bold"
              >
                {displayName.slice(0, 1)}
              </span>
              <div className="min-w-0">
                <p className="text-lg font-bold text-ink truncate">{displayName}</p>
                <div className="flex flex-wrap items-center gap-1.5 mt-1">
                  {(profile.age as number) != null && (
                    <Badge tone="primary">
                      <Cake aria-hidden className="h-3 w-3" />
                      {profile.age as number} 岁
                    </Badge>
                  )}
                  {genderLabel && <Badge tone="neutral">{genderLabel}</Badge>}
                </div>
              </div>
            </div>

            <p className="text-sm font-medium text-muted mb-1.5">兴趣爱好</p>
            <div className="flex flex-wrap gap-1.5 mb-4">
              {interestChips.length === 0 ? (
                <span className="text-muted text-sm">还没填写，右边补上吧</span>
              ) : (
                interestChips.map((it) => (
                  <Badge key={it} tone="primary">
                    <Target aria-hidden className="h-3 w-3" />
                    {it}
                  </Badge>
                ))
              )}
            </div>

            <p className="text-sm font-medium text-muted mb-1.5">健康情况</p>
            <div className="flex flex-wrap gap-1.5">
              {healthChips.length === 0 ? (
                <span className="text-muted text-sm">还没填写</span>
              ) : (
                healthChips.map((h) => (
                  <Badge key={h} tone="warning">
                    <Pill aria-hidden className="h-3 w-3" />
                    {h}
                  </Badge>
                ))
              )}
            </div>
          </SectionCard>

          <InviteCodeCard />
          <MoodCalendar />
        </div>

        {/* 右栏：编辑资料 + AI 记忆 */}
        <div className="space-y-5">
          <SectionCard
            title="编辑资料"
            icon={<UserRound aria-hidden className="h-5 w-5" />}
            meta="随时可以修改"
          >
            <form onSubmit={handleSave} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="p-name" className="block mb-1 font-medium text-ink">
                    姓名/称呼
                  </label>
                  <input
                    id="p-name"
                    type="text"
                    value={(profile.name as string) || ''}
                    onChange={(e) => updateField('name', e.target.value)}
                    className="w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none bg-card"
                  />
                </div>
                <div>
                  <label htmlFor="p-age" className="block mb-1 font-medium text-ink">
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
                    className="w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none bg-card"
                  />
                </div>
                <div>
                  <label htmlFor="p-gender" className="block mb-1 font-medium text-ink">
                    性别
                  </label>
                  <select
                    id="p-gender"
                    value={(profile.gender as string) || ''}
                    onChange={(e) => updateField('gender', e.target.value)}
                    className="w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none bg-card"
                  >
                    <option value="">请选择</option>
                    <option value="male">男</option>
                    <option value="female">女</option>
                    <option value="other">其他</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="p-interests" className="block mb-1 font-medium text-ink">
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
                    className="w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none bg-card"
                  />
                </div>
              </div>
              <div>
                <label htmlFor="p-health" className="block mb-1 font-medium text-ink">
                  健康情况
                </label>
                <textarea
                  id="p-health"
                  rows={3}
                  value={(profile.health as string) || ''}
                  onChange={(e) => updateField('health', e.target.value)}
                  placeholder="如：有高血压，腿脚不太方便..."
                  className="w-full px-3 py-2 rounded-input border border-hairline focus:border-primary outline-none resize-none bg-card"
                />
              </div>

              {message && (
                <div className="bg-success-soft text-success rounded-btn px-4 py-2">
                  {message}
                </div>
              )}
              {error && (
                <div className="bg-danger-soft text-danger rounded-btn px-4 py-2">
                  {error}
                </div>
              )}

              <LargeButton type="submit" size="lg" disabled={saving} className="w-full md:w-auto">
                <Save aria-hidden className="h-5 w-5" />
                {saving ? '保存中...' : '保存画像'}
              </LargeButton>
            </form>
          </SectionCard>

          <SectionCard
            title="AI 记住的事"
            icon={<Brain aria-hidden className="h-5 w-5" />}
            meta={`${memories.length} 条`}
            actions={
              <button
                type="button"
                onClick={refreshMemories}
                className="min-h-[40px] px-4 rounded-btn bg-primary-soft hover:bg-primary hover:text-on-primary text-primary font-medium flex items-center gap-1.5 transition-colors"
                title="聊天后 AI 会在后台整理记忆，点这里刷新"
              >
                <RefreshCw aria-hidden className="h-4 w-4" />
                刷新
              </button>
            }
          >
            <p className="text-sm text-muted mb-4 bg-lilac-soft rounded-btn px-3 py-2">
              上面是您主动填的「画像」，AI 每次聊天都会参考。这里是聊天中 AI <b>自动记下</b>的关键事，
              比如「女儿叫小芳」「喜欢邓丽君」。聊天后等几秒点刷新能看到新记忆。
            </p>
            {memories.length === 0 ? (
              <EmptyState
                icon={<Brain aria-hidden className="h-6 w-6" />}
                title="还没有自动记下的事"
                description="多聊几次，AI 会把重要的事记在这里。"
              />
            ) : (
              <MemoryList memories={memories} onDelete={handleDeleteMemory} />
            )}
          </SectionCard>
        </div>
      </div>
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
    <SectionCard title="我的邀请码" icon={<KeyRound aria-hidden className="h-5 w-5" />}>
      <p className="text-sm text-muted mb-3">
        把这个码告诉家人，他们就能绑定查看您的状态。
      </p>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setShow(!show)}
          className="min-h-[44px] px-4 rounded-btn bg-primary text-on-primary font-bold text-sm"
        >
          {show ? '隐藏' : '显示'}
        </button>
        {show && (
          <p className="flex-1 min-w-0 text-center bg-card rounded-btn px-4 py-2 text-2xl font-mono font-bold text-primary tracking-widest truncate">
            {code}
          </p>
        )}
      </div>
    </SectionCard>
  );
}

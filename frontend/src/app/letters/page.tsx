'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, TimeLetter, letterApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { useServerEvents } from '@/lib/events';
import { LargeButton } from '@/components/LargeButton';

const inputCls =
  'w-full min-h-[52px] rounded-xl border-2 border-warm-light px-4 text-lg text-gray-900 ' +
  'focus:outline-none focus:border-warm-primary bg-white';

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function defaultDeliverAt(): string {
  const d = new Date();
  d.setFullYear(d.getFullYear() + 1);
  d.setHours(9, 0, 0, 0);
  return toLocalInput(d);
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}

function countdown(l: TimeLetter): string {
  if (l.status !== 'scheduled') return '';
  if (l.days_until >= 1) return `还有 ${l.days_until} 天`;
  const hours = Math.max(1, Math.floor(l.seconds_until / 3600));
  return `还有 ${hours} 小时`;
}

/** 老人端「时光信笺」：写给未来的自己或家人。 */
export default function LettersPage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);

  const [hydrated, setHydrated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [scheduled, setScheduled] = useState<TimeLetter[]>([]);
  const [delivered, setDelivered] = useState<TimeLetter[]>([]);
  const [read, setRead] = useState<TimeLetter[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');

  const [editingId, setEditingId] = useState<number | null>(null);
  const [recipientType, setRecipientType] = useState<'self' | 'family'>('self');
  const [recipientName, setRecipientName] = useState('');
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [deliverAt, setDeliverAt] = useState(defaultDeliverAt());
  const [visibility, setVisibility] = useState<'private' | 'family'>('private');
  const [showForm, setShowForm] = useState(false);

  const formRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => setHydrated(true), []);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.push('/login');
      return;
    }
    if (user?.role === 'family') {
      router.push('/family');
    }
  }, [hydrated, accessToken, user, router]);

  const load = useCallback(async () => {
    try {
      const res = await letterApi.list();
      setScheduled(res.scheduled);
      setDelivered(res.delivered);
      setRead(res.read);
      setError('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载失败，稍后再试试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hydrated || !accessToken || user?.role === 'family') return;
    load();
  }, [hydrated, accessToken, user, load]);

  // 到点的信由后端定时投递并推 SSE：正在看页面时自动刷出"可以拆了"
  useServerEvents(
    accessToken,
    (e) => {
      if (e.type === 'time_letter') load();
    },
    user?.role === 'elderly'
  );

  if (!hydrated || !accessToken) return null;

  const resetForm = () => {
    setEditingId(null);
    setRecipientType('self');
    setRecipientName('');
    setTitle('');
    setContent('');
    setDeliverAt(defaultDeliverAt());
    setVisibility('private');
  };

  const startEdit = (l: TimeLetter) => {
    setEditingId(l.id);
    setRecipientType(l.recipient_type);
    setRecipientName(l.recipient_name);
    setTitle(l.title);
    setContent(l.content);
    setDeliverAt(toLocalInput(new Date(l.deliver_at)));
    setVisibility(l.visibility);
    setShowForm(true);
    setNotice('');
    setTimeout(() => formRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy('save');
    setError('');
    try {
      const payload = {
        title: title.trim(),
        content: content.trim(),
        recipient_type: recipientType,
        recipient_name: recipientName.trim(),
        deliver_at: deliverAt,
        visibility,
      };
      if (editingId !== null) {
        await letterApi.update(editingId, payload);
        setNotice('这封信改好了。');
      } else {
        await letterApi.create(payload);
        setNotice('信收好了，到日子才会打开。');
      }
      resetForm();
      setShowForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败');
    } finally {
      setBusy('');
    }
  };

  const handleOpen = async (l: TimeLetter) => {
    setBusy(`open-${l.id}`);
    try {
      await letterApi.open(l.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '拆信失败');
    } finally {
      setBusy('');
    }
  };

  const handleDelete = async (l: TimeLetter) => {
    if (!window.confirm('这封信还没送出去，确定删掉吗？删了就找不回来了。')) return;
    setBusy(`del-${l.id}`);
    try {
      await letterApi.remove(l.id);
      if (editingId === l.id) {
        resetForm();
        setShowForm(false);
      }
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-600">
            写给未来
          </p>
          <h1 className="text-3xl font-bold text-gray-900 mt-1">💌 时光信笺</h1>
          <p className="text-gray-500 mt-1">
            现在写一句话，锁起来。到了那天，你或者家人才能打开。
          </p>
        </div>
        <LargeButton
          onClick={() => {
            setShowForm((v) => !v);
            if (!showForm) resetForm();
          }}
        >
          {showForm ? '收起' : '✍️ 写一封信'}
        </LargeButton>
      </div>

      {error && (
        <div className="rounded-xl bg-rose-50 border-2 border-rose-200 text-rose-700 px-4 py-3">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-xl bg-emerald-50 border-2 border-emerald-200 text-emerald-700 px-4 py-3">
          {notice}
        </div>
      )}

      {showForm && (
        <section
          ref={formRef}
          className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-5"
        >
          <h2 className="text-xl font-bold text-gray-900">
            {editingId !== null ? '改这封信' : '写一封新的'}
          </h2>
          <form onSubmit={handleSubmit} className="mt-4 space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setRecipientType('self')}
                className={`min-h-[56px] rounded-xl border-2 text-lg font-medium ${
                  recipientType === 'self'
                    ? 'border-warm-primary bg-warm-light text-warm-dark'
                    : 'border-warm-light bg-white text-gray-600'
                }`}
              >
                🧓 给未来的自己
              </button>
              <button
                type="button"
                onClick={() => setRecipientType('family')}
                className={`min-h-[56px] rounded-xl border-2 text-lg font-medium ${
                  recipientType === 'family'
                    ? 'border-warm-primary bg-warm-light text-warm-dark'
                    : 'border-warm-light bg-white text-gray-600'
                }`}
              >
                👨‍👩‍👧 给家人
              </button>
            </div>

            {recipientType === 'family' && (
              <label className="block">
                <span className="text-sm text-gray-600">给谁（写个称呼）</span>
                <input
                  className={inputCls}
                  value={recipientName}
                  onChange={(e) => setRecipientName(e.target.value)}
                  placeholder="比如：女儿小芳"
                  required
                />
              </label>
            )}

            <label className="block">
              <span className="text-sm text-gray-600">标题（可不填）</span>
              <input
                className={inputCls}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="比如：等我八十岁那年再看"
              />
            </label>

            <label className="block">
              <span className="text-sm text-gray-600">想说的话</span>
              <textarea
                className="w-full min-h-[160px] rounded-xl border-2 border-warm-light px-4 py-3 text-lg text-gray-900 focus:outline-none focus:border-warm-primary"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="慢慢写，想到什么写什么…"
                required
              />
            </label>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="block">
                <span className="text-sm text-gray-600">哪天打开</span>
                <input
                  className={inputCls}
                  type="datetime-local"
                  value={deliverAt}
                  onChange={(e) => setDeliverAt(e.target.value)}
                  required
                />
              </label>
              <div>
                <span className="text-sm text-gray-600">到时候谁能看</span>
                <div className="mt-1 grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setVisibility('private')}
                    className={`min-h-[52px] rounded-xl border-2 text-base ${
                      visibility === 'private'
                        ? 'border-warm-primary bg-warm-light text-warm-dark'
                        : 'border-warm-light bg-white text-gray-600'
                    }`}
                  >
                    🔒 只有我
                  </button>
                  <button
                    type="button"
                    onClick={() => setVisibility('family')}
                    className={`min-h-[52px] rounded-xl border-2 text-base ${
                      visibility === 'family'
                        ? 'border-warm-primary bg-warm-light text-warm-dark'
                        : 'border-warm-light bg-white text-gray-600'
                    }`}
                  >
                    👨‍👩‍👧 家人也能看
                  </button>
                </div>
              </div>
            </div>

            <p className="text-sm text-gray-500">
              没到日子之前，信的内容谁也看不到，家人也看不到。到了那天才会打开。
            </p>

            <div className="flex gap-3 flex-wrap">
              <LargeButton type="submit" size="lg" disabled={busy === 'save'}>
                {busy === 'save' ? '保存中…' : editingId !== null ? '改好了' : '封起来'}
              </LargeButton>
              {editingId !== null && (
                <LargeButton
                  type="button"
                  variant="ghost"
                  size="lg"
                  onClick={() => {
                    resetForm();
                    setShowForm(false);
                  }}
                >
                  不改了
                </LargeButton>
              )}
            </div>
          </form>
        </section>
      )}

      {loading ? (
        <p className="text-center text-gray-500 py-12 text-lg">正在翻看你的信…</p>
      ) : (
        <>
          {/* 到点了、还没拆 */}
          {delivered.length > 0 && (
            <section className="bg-amber-50 rounded-2xl border-2 border-amber-300 p-5">
              <h2 className="text-xl font-bold text-gray-900">✉️ 有信可以拆了</h2>
              <ul className="mt-4 space-y-3">
                {delivered.map((l) => (
                  <li key={l.id} className="bg-white rounded-xl border border-amber-200 p-4">
                    <p className="text-lg font-bold text-gray-900">
                      {l.title || '一封信'}
                      <span className="ml-2 text-sm font-normal text-gray-500">
                        {l.recipient_type === 'family'
                          ? `写给${l.recipient_name || '家人'}`
                          : '写给未来的自己'}
                      </span>
                    </p>
                    <p className="text-sm text-gray-500 mt-1">
                      写于 {fmtDate(l.created_at)} · {fmtDate(l.deliver_at)} 到
                    </p>
                    <LargeButton
                      className="mt-3"
                      disabled={busy === `open-${l.id}`}
                      onClick={() => handleOpen(l)}
                    >
                      {busy === `open-${l.id}` ? '拆着呢…' : '拆开看看'}
                    </LargeButton>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* 未到时间 */}
          <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-5">
            <h2 className="text-xl font-bold text-gray-900">🔒 还没到日子的信</h2>
            {scheduled.length === 0 ? (
              <p className="text-gray-600 mt-3">还没有封起来的信。想写就点右上角。</p>
            ) : (
              <ul className="mt-4 space-y-3">
                {scheduled.map((l) => (
                  <li
                    key={l.id}
                    className="rounded-xl border-2 border-warm-light bg-warm-light/20 px-4 py-4"
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div>
                        <p className="text-lg font-bold text-gray-900">
                          {l.title || '一封信'}
                          <span className="ml-2 text-sm font-normal text-gray-500">
                            {l.recipient_type === 'family'
                              ? `写给${l.recipient_name || '家人'}`
                              : '写给未来的自己'}
                          </span>
                        </p>
                        <p className="text-sm text-gray-600 mt-1">
                          {fmtDate(l.deliver_at)} 打开 · {countdown(l)} ·{' '}
                          {l.visibility === 'family' ? '家人也能看' : '只有我能看'}
                        </p>
                        <p className="text-sm text-gray-400 mt-1">内容封存中，到日子才能看</p>
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={() => startEdit(l)}
                          className="min-h-[44px] px-3 rounded-lg text-warm-dark hover:bg-warm-light"
                        >
                          改一下
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(l)}
                          disabled={busy === `del-${l.id}`}
                          className="min-h-[44px] px-3 rounded-lg text-rose-600 hover:bg-rose-50"
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 拆过的 */}
          {read.length > 0 && (
            <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-5">
              <h2 className="text-xl font-bold text-gray-900">📖 拆过的信</h2>
              <ul className="mt-4 space-y-4">
                {read.map((l) => (
                  <li key={l.id} className="rounded-xl bg-warm-light/30 border border-warm-light p-4">
                    <p className="text-lg font-bold text-gray-900">
                      {l.title || '一封信'}
                    </p>
                    <p className="text-sm text-gray-500 mt-1">
                      {l.recipient_type === 'family'
                        ? `写给${l.recipient_name || '家人'}`
                        : '写给未来的自己'}{' '}
                      · {fmtDate(l.deliver_at)} 打开
                    </p>
                    <p className="mt-3 text-gray-800 whitespace-pre-wrap leading-relaxed">
                      {l.content}
                    </p>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

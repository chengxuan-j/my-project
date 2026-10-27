'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { DueReminder, healthCareApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { useCareStore } from '@/stores/care';
import { useServerEvents } from '@/lib/events';
import { LargeButton } from '@/components/LargeButton';

const POLL_MS = 30_000;
const SNOOZE_MS = 10 * 60 * 1000;
const SNOOZE_KEY = 'care-snooze-until';

/** 共享 AudioContext：浏览器只允许"用户点过页面之后"出声，
 *  所以在第一次 pointerdown 时把它解锁，之后到点提醒才响得出来。 */
let sharedCtx: AudioContext | null = null;

function getAudioCtx(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!sharedCtx) {
    const AC =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    try {
      sharedCtx = new AC();
    } catch {
      return null;
    }
  }
  return sharedCtx;
}

function unlockAudio() {
  const ctx = getAudioCtx();
  if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => undefined);
}

/** 三声短提示音。浏览器仍不允许出声时静默失败——视觉提示仍然在。 */
function playAlertTone() {
  const ctx = getAudioCtx();
  if (!ctx) return;
  const fire = () => {
    try {
      const start = ctx.currentTime + 0.05;
      [0, 0.38, 0.76].forEach((offset) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = 'sine';
        osc.frequency.value = 880;
        gain.gain.setValueAtTime(0.0001, start + offset);
        gain.gain.exponentialRampToValueAtTime(0.25, start + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + offset + 0.28);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(start + offset);
        osc.stop(start + offset + 0.3);
      });
    } catch {
      // 忽略
    }
  };
  if (ctx.state === 'suspended') {
    ctx.resume().then(fire).catch(() => undefined);
  } else {
    fire();
  }
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

/**
 * 全局强提醒弹窗：吃药 / 复诊到点后，不管老人在哪个页面都会盖上来。
 *
 * 为什么做成"挡住全屏"而不是页面里一行卡片：
 * 老人不会主动去找提醒，页面顶部的浅色条很容易被忽略。吃药这件事漏一次
 * 就可能有后果，所以宁可按"必须处理一下才能继续"来做——但保留「10 分钟后再
 * 提醒」，避免正在做别的事时被彻底打断。
 */
export function CareAlertModal() {
  const pathname = usePathname();
  const { accessToken, user } = useAuthStore();
  const setDueCount = useCareStore((s) => s.setDueCount);
  const preview = useCareStore((s) => s.preview);
  const clearPreview = useCareStore((s) => s.clearPreview);
  const [items, setItems] = useState<DueReminder[]>([]);
  const [snoozeUntil, setSnoozeUntil] = useState(0);
  const [busyKey, setBusyKey] = useState('');
  const [error, setError] = useState('');
  const lastAlertRef = useRef('');
  const originalTitleRef = useRef('');

  const isElderly = user?.role === 'elderly';

  const load = useCallback(async () => {
    if (!accessToken || !isElderly) return;
    try {
      const res = await healthCareApi.due();
      setItems(res.items);
      setDueCount(res.count);
    } catch {
      // 网络抖动不打扰老人，下一轮再试
    }
  }, [accessToken, isElderly, setDueCount]);

  // 首屏 + 轮询 + SSE 即时刷新
  useEffect(() => {
    if (!accessToken || !isElderly) return;
    load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [accessToken, isElderly, load]);

  useServerEvents(accessToken, (e) => {
    if (e.type === 'health_reminder') load();
  }, !!isElderly);

  // 恢复未过期的"稍后提醒"
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const raw = window.localStorage.getItem(SNOOZE_KEY);
    const until = raw ? Number(raw) : 0;
    if (until > Date.now()) setSnoozeUntil(until);
    else window.localStorage.removeItem(SNOOZE_KEY);
  }, []);

  // 第一次点页面时解锁音频，之后提醒响得出来
  useEffect(() => {
    if (!isElderly) return;
    document.addEventListener('pointerdown', unlockAudio);
    return () => document.removeEventListener('pointerdown', unlockAudio);
  }, [isElderly]);

  const hiddenPage = pathname === '/login' || pathname === '/register';
  const shownItems = preview ?? items;
  const visible =
    isElderly &&
    !hiddenPage &&
    shownItems.length > 0 &&
    (preview ? true : Date.now() >= snoozeUntil);

  // 弹出来时：响三声 + 标题提醒（切到别的标签页也能看到）
  useEffect(() => {
    if (!visible) {
      if (originalTitleRef.current) {
        document.title = originalTitleRef.current;
        originalTitleRef.current = '';
      }
      return;
    }
    const signature = shownItems.map((i) => i.key).join('|');
    if (signature && signature !== lastAlertRef.current) {
      lastAlertRef.current = signature;
      playAlertTone();
    }
    if (!originalTitleRef.current) originalTitleRef.current = document.title;
    document.title = `(${shownItems.length}) 该吃药了 · 陪伴 AI`;
  }, [visible, shownItems]);

  const snooze = () => {
    if (preview) {
      clearPreview();
      return;
    }
    const until = Date.now() + SNOOZE_MS;
    setSnoozeUntil(until);
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(SNOOZE_KEY, String(until));
    }
    setTimeout(() => {
      setSnoozeUntil(0);
      if (typeof window !== 'undefined') window.localStorage.removeItem(SNOOZE_KEY);
    }, SNOOZE_MS);
  };

  const ack = async (item: DueReminder) => {
    if (preview) {
      clearPreview();
      return;
    }
    setBusyKey(item.key);
    setError('');
    try {
      await healthCareApi.ack({
        kind: item.kind,
        ref_id: item.ref_id,
        scheduled_for: item.scheduled_for,
      });
      lastAlertRef.current = '';
      await load();
    } catch {
      setError('没确认成功，请再点一次');
    } finally {
      setBusyKey('');
    }
  };

  if (!visible) return null;

  const hasMed = shownItems.some((i) => i.kind === 'medication');
  const title = hasMed
    ? shownItems.length > 1
      ? `有 ${shownItems.length} 件事该做了`
      : '该吃药了'
    : '该去复诊了';

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[70] bg-black/55 backdrop-blur-sm flex items-center justify-center p-4"
    >
      <div className="w-full max-w-lg bg-white rounded-3xl border-4 border-rose-400 shadow-2xl overflow-hidden">
        {/* 顶部警示条 */}
        <div className="bg-rose-500 text-white px-6 py-4 flex items-center gap-3">
          <span className="text-3xl animate-bounce" aria-hidden>
            🔔
          </span>
          <div>
            <p className="text-2xl font-bold leading-tight">{title}</p>
            <p className="text-rose-50 text-sm mt-0.5">
              {preview ? '这是试看效果，不会真的记录' : '这事别忘了，处理完再点下面的按钮'}
            </p>
          </div>
        </div>

        <div className="p-5 space-y-3 max-h-[55vh] overflow-y-auto">
          {shownItems.map((item) => (
            <div
              key={item.key}
              className="rounded-2xl border-2 border-amber-300 bg-amber-50 px-4 py-4"
            >
              <p className="text-2xl font-bold text-gray-900">
                {item.kind === 'medication' ? '💊 ' : '🏥 '}
                {item.title}
              </p>
              {item.detail && <p className="text-lg text-gray-700 mt-1">{item.detail}</p>}
              <p className="text-base text-rose-700 font-medium mt-2">
                原定 {fmtClock(item.scheduled_for)}
                {(item.overdue_minutes ?? 0) > 0
                  ? ` · 已经过了 ${item.overdue_minutes} 分钟`
                  : ' · 到点了'}
              </p>
              <LargeButton
                size="xl"
                className="w-full mt-3"
                disabled={busyKey === item.key}
                onClick={() => ack(item)}
              >
                {busyKey === item.key
                  ? '记着呢…'
                  : item.kind === 'medication'
                    ? '✅ 我吃过了'
                    : '✅ 我知道了'}
              </LargeButton>
            </div>
          ))}
          {error && <p className="text-rose-600 text-center">{error}</p>}
        </div>

        <div className="px-5 pb-5">
          <LargeButton
            variant="secondary"
            size="lg"
            className="w-full"
            onClick={snooze}
          >
            {preview ? '关闭预览' : '⏰ 过 10 分钟再提醒我'}
          </LargeButton>
          <p className="text-center text-sm text-gray-500 mt-2">
            {preview
              ? '这是试看效果，点按钮不会真的记录'
              : '点上面的按钮确认后，这条提醒就消掉了'}
          </p>
        </div>
      </div>
    </div>
  );
}

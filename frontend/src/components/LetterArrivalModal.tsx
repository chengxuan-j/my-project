'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname } from 'next/navigation';
import { letterApi, TimeLetter } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { useServerEvents } from '@/lib/events';

const SNOOZE_MS = 30 * 60 * 1000;

function isSnoozed(id: number): boolean {
  try {
    const until = Number(sessionStorage.getItem(`letter_snooze_${id}`) || 0);
    return until > Date.now();
  } catch {
    return false;
  }
}

function playChime() {
  try {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AC();
    [523.25, 659.25, 783.99].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = freq;
      osc.connect(gain);
      gain.connect(ctx.destination);
      const t = ctx.currentTime + i * 0.09;
      gain.gain.setValueAtTime(0, t);
      gain.gain.linearRampToValueAtTime(0.07, t + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, t + 0.7);
      osc.start(t);
      osc.stop(t + 0.75);
    });
    window.setTimeout(() => void ctx.close(), 1400);
  } catch {
    // 浏览器不支持音频也不影响弹窗
  }
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * 时光信笺到点自动弹出。
 *
 * 投递：/letters/due 返回"已到点但没拆开"的信；
 * 实时：后端投递任务发 SSE time_letter，收到就立刻再查一次；
 * 兜底：45 秒轮询一次（SSE 断线也能弹）。
 *
 * 交互：先看到浮在时光里的信封，点"拆开"才调 /letters/{id}/open，
 * 然后信纸展开、正文逐段浮出。可以"稍后再看"（30 分钟内不再弹这封）。
 */
export function LetterArrivalModal() {
  const { user, accessToken } = useAuthStore();
  const pathname = usePathname();
  const [queue, setQueue] = useState<TimeLetter[]>([]);
  const [stage, setStage] = useState<'sealed' | 'opening' | 'reading'>('sealed');
  const [error, setError] = useState('');
  const [opening, setOpening] = useState(false);
  const timers = useRef<number[]>([]);

  const loadDue = useCallback(async () => {
    if (!accessToken || user?.role !== 'elderly') return;
    try {
      const res = await letterApi.due();
      setQueue((res.letters || []).filter((l) => !isSnoozed(l.id)));
    } catch {
      // 网络抖动不打扰老人
    }
  }, [accessToken, user?.role]);

  useEffect(() => {
    if (!accessToken || user?.role !== 'elderly') {
      setQueue([]);
      return;
    }
    void loadDue();
    const timer = window.setInterval(() => void loadDue(), 45_000);
    return () => window.clearInterval(timer);
  }, [accessToken, user?.role, loadDue]);

  useServerEvents(
    accessToken,
    (event) => {
      if (event.type === 'time_letter') void loadDue();
    },
    !!accessToken && user?.role === 'elderly'
  );

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const letter = queue[0];
  const hidden = !letter || user?.role !== 'elderly' || pathname === '/letters';

  const snooze = () => {
    if (!letter) return;
    try {
      sessionStorage.setItem(`letter_snooze_${letter.id}`, String(Date.now() + SNOOZE_MS));
    } catch {
      // 忽略隐私模式限制
    }
    setQueue((q) => q.slice(1));
    setStage('sealed');
    setError('');
  };

  const open = async () => {
    if (!letter || opening) return;
    setOpening(true);
    setError('');
    playChime();
    try {
      await letterApi.open(letter.id);
      setStage('opening');
      timers.current.push(
        window.setTimeout(() => setStage('reading'), 1150)
      );
    } catch {
      setError('这封信暂时打不开，稍后再试试');
      setStage('sealed');
    } finally {
      setOpening(false);
    }
  };

  const finish = () => {
    setQueue((q) => q.slice(1));
    setStage('sealed');
    setError('');
    void loadDue();
  };

  if (hidden || !letter) return null;

  const title = letter.title?.trim() || '一封写给你的信';
  const content = letter.content || '';

  return (
    <div className="letter-travel fixed inset-0 z-[65] flex items-center justify-center overflow-hidden px-4">
      <style>{`
        .letter-travel{background:radial-gradient(120% 90% at 50% 0%,#4a2f1b 0%,#2a1a10 45%,#140d08 100%);}
        .lt-stars{position:absolute;inset:0;pointer-events:none;opacity:.55}
        .lt-stars span{position:absolute;width:3px;height:3px;border-radius:9999px;background:#ffd79a;
          box-shadow:0 0 10px 2px rgba(255,196,110,.45);animation:ltTwinkle 4s ease-in-out infinite}
        @keyframes ltTwinkle{0%,100%{opacity:.15;transform:scale(.8)}50%{opacity:.9;transform:scale(1.2)}}
        .lt-ring{position:absolute;left:50%;top:50%;border-radius:9999px;border:1px solid rgba(255,205,130,.25);
          transform:translate(-50%,-50%);animation:ltSpin 24s linear infinite}
        .lt-ring.r2{border-style:dashed;border-color:rgba(255,205,130,.18);animation-duration:38s;animation-direction:reverse}
        @keyframes ltSpin{to{transform:translate(-50%,-50%) rotate(360deg)}}
        .lt-halo{position:absolute;left:50%;top:48%;width:520px;height:520px;transform:translate(-50%,-50%);
          background:radial-gradient(circle,rgba(255,190,100,.28),rgba(255,190,100,0) 62%);filter:blur(6px);
          animation:ltBreathe 5s ease-in-out infinite}
        @keyframes ltBreathe{0%,100%{opacity:.55;transform:translate(-50%,-50%) scale(.95)}50%{opacity:1;transform:translate(-50%,-50%) scale(1.06)}}
        .lt-envelope{position:relative;width:276px;height:184px;border-radius:16px;
          background:linear-gradient(160deg,#e8c48d,#c9955a);box-shadow:0 30px 70px rgba(0,0,0,.55),inset 0 0 40px rgba(120,70,20,.25);
          animation:ltFloat 4.2s ease-in-out infinite}
        @keyframes ltFloat{0%,100%{transform:translateY(0) rotate(-1deg)}50%{transform:translateY(-12px) rotate(1deg)}}
        .lt-envelope::before{content:'';position:absolute;inset:0;border-radius:16px;
          background:repeating-linear-gradient(45deg,rgba(255,255,255,.06) 0 8px,rgba(0,0,0,.03) 8px 16px)}
        .lt-flap{position:absolute;top:0;left:0;width:0;height:0;border-left:138px solid transparent;
          border-right:138px solid transparent;border-top:96px solid #d8a76a;filter:drop-shadow(0 6px 8px rgba(0,0,0,.18));
          transform-origin:top center}
        .lt-flap.open{animation:ltFlap 1s ease forwards}
        @keyframes ltFlap{to{transform:rotateX(180deg)}}
        .lt-seal{position:absolute;left:50%;top:86px;transform:translateX(-50%);width:54px;height:54px;border-radius:9999px;
          background:radial-gradient(circle at 35% 30%,#b8482f,#7e2416);color:#ffe9c9;display:flex;align-items:center;
          justify-content:center;font-size:20px;letter-spacing:2px;box-shadow:0 6px 18px rgba(0,0,0,.35),inset 0 0 8px rgba(255,220,170,.35)}
        .lt-paper{position:relative;width:min(560px,92vw);max-height:78vh;overflow:auto;border-radius:10px;
          background:linear-gradient(180deg,#fffaf0,#f8ecd4);color:#4a3523;padding:34px 30px 26px;
          box-shadow:0 40px 90px rgba(0,0,0,.6),inset 0 0 60px rgba(180,130,60,.12);
          animation:ltUnfold .9s cubic-bezier(.2,.8,.2,1) both}
        @keyframes ltUnfold{from{opacity:0;transform:perspective(1200px) rotateX(-55deg) translateY(40px) scale(.9)}
          to{opacity:1;transform:perspective(1200px) rotateX(0) translateY(0) scale(1)}}
        .lt-paper::before{content:'';position:absolute;inset:0;border-radius:10px;pointer-events:none;
          background:repeating-linear-gradient(0deg,rgba(160,120,60,.05) 0 1px,transparent 1px 30px)}
        .lt-line{opacity:0;animation:ltInk .9s ease forwards}
        @keyframes ltInk{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
      `}</style>

      <div className="lt-halo" />
      <div className="lt-ring" style={{ width: 620, height: 620 }} />
      <div className="lt-ring r2" style={{ width: 760, height: 760 }} />
      <div className="lt-stars" aria-hidden>
        {Array.from({ length: 22 }).map((_, i) => (
          <span
            key={i}
            style={{
              left: `${(i * 37) % 100}%`,
              top: `${(i * 53) % 100}%`,
              animationDelay: `${(i % 7) * 0.4}s`,
            }}
          />
        ))}
      </div>

      {stage !== 'reading' ? (
        <div className="relative z-10 flex flex-col items-center">
          <p className="text-amber-200/80 tracking-[0.35em] text-sm mb-6">时 光 信 笺</p>
          <div className="lt-envelope" onClick={open} role="button" tabIndex={0}
               onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') void open(); }}>
            <div className={`lt-flap ${stage === 'opening' ? 'open' : ''}`} />
            <div className="lt-seal">时</div>
          </div>

          <h2 className="mt-8 text-2xl md:text-3xl font-bold text-amber-50 text-center">
            有一封来自时光里的信
          </h2>
          <p className="mt-2 text-amber-100/70 text-center">
            {formatDate(letter.deliver_at)} 写下的 · 今天到站
          </p>

          {error && <p className="mt-3 text-red-200 text-sm">{error}</p>}

          <div className="mt-7 flex items-center gap-3">
            <button
              onClick={open}
              disabled={opening}
              className="min-h-[56px] px-8 rounded-full bg-gradient-to-r from-amber-400 to-orange-500 text-[#3a220f] font-bold text-lg shadow-[0_12px_30px_rgba(255,170,60,.35)] hover:brightness-110 disabled:opacity-60"
            >
              {opening ? '正在拆开…' : '拆开这封信'}
            </button>
            <button
              onClick={snooze}
              className="min-h-[56px] px-5 rounded-full border border-amber-200/40 text-amber-100/80 hover:bg-white/10"
            >
              稍后再看
            </button>
          </div>
          <p className="mt-4 text-xs text-amber-100/40">30 分钟内不再提醒</p>
        </div>
      ) : (
        <article className="lt-paper relative z-10">
          <div className="lt-line flex items-center justify-between text-xs text-amber-800/60"
               style={{ animationDelay: '0.15s' }}>
            <span>{formatDate(letter.deliver_at)}</span>
            <span>{letter.recipient_type === 'family' ? `写给 ${letter.recipient_name}` : '写给未来的自己'}</span>
          </div>
          <h2 className="lt-line mt-5 text-2xl md:text-3xl font-bold text-[#5b3a1e]"
              style={{ animationDelay: '0.3s' }}>
            {title}
          </h2>
          <div className="lt-line mt-4 h-px bg-amber-800/20" style={{ animationDelay: '0.45s' }} />
          <div className="mt-5 space-y-4 text-lg leading-8 text-[#4a3523]">
            {content.split(/\n+/).filter(Boolean).map((p, i) => (
              <p key={i} className="lt-line" style={{ animationDelay: `${0.6 + i * 0.22}s` }}>
                {p}
              </p>
            ))}
          </div>
          <div className="lt-line mt-8 flex items-center justify-between text-sm text-amber-800/60"
               style={{ animationDelay: `${0.9 + content.split(/\n+/).length * 0.22}s` }}>
            <span>时间替你保管到今天</span>
            <button
              onClick={finish}
              className="min-h-[52px] px-6 rounded-full bg-[#7e4a22] text-amber-50 font-semibold hover:bg-[#683a18]"
            >
              收好这封信
            </button>
          </div>
        </article>
      )}
    </div>
  );
}

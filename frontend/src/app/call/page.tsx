'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { ApiError, chatApi, settingsApi, speechApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

type Stage = 'idle' | 'listening' | 'thinking' | 'speaking';

const FALLBACK_DIALECTS = ['普通话', '四川话', '东北话', '粤语', '上海话', '河南话', '陕西话'];

/** 预生成的方言示例录音（public/voice-samples 下），不会说方言也能试完整流程。 */
const SAMPLES = [
  { key: 'sichuan', dialect: '四川话', label: '四川话示例' },
  { key: 'yue', dialect: '粤语', label: '粤语示例' },
  { key: 'shanxi', dialect: '陕西话', label: '陕西话示例' },
];

const STAGE_TEXT: Record<Stage, string> = {
  idle: '点一下话筒，或者上传一段录音',
  listening: '我在听，说完停一下就行',
  thinking: '我想想…',
  speaking: '我在说',
};

/** 把服务端的原始错误翻成老人看得懂的话（欠费时会返回一大段英文 JSON）。 */
function friendly(msg: string): string {
  if (/Arrearage|Access denied|overdue|good standing/i.test(msg)) {
    return '语音服务暂时不可用（账号欠费或额度用完了），请联系管理员充值后再试';
  }
  if (/超时|timeout/i.test(msg)) return '等太久没结果，再说一次吧';
  if (/未识别到有效语音|静音/i.test(msg)) return '没听清，再说一次吧';
  return msg;
}

function mmss(total: number) {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/**
 * 语音通话页：一轮一答的免提对话。
 *
 * 链路：录音/上传 → 一次性转写（/speech/asr/transcribe）→ 流式回复
 *       → 逐句 TTS 排队播放 → 播完自动继续听。
 *
 * 方言：这里的方言选择会写回账号设置，所以识别（fun-asr）、
 *       回复用词（prompt 注入）、播报腔调（TTS 指令）三处一起生效。
 *       不会说方言也没关系：可以点示例录音，或上传一段方言音频。
 */
export default function CallPage() {
  const router = useRouter();
  const { user, accessToken } = useAuthStore();

  const [hydrated, setHydrated] = useState(false);
  const [dialect, setDialect] = useState('普通话');
  const [options, setOptions] = useState<string[]>(FALLBACK_DIALECTS);
  // 没有原生方言音色的（东北话/河南话）：文字用方言词，播报仍是普通话，要如实提示
  const [voiceMap, setVoiceMap] = useState<Record<string, boolean>>({});
  const [stage, setStage] = useState<Stage>('idle');
  const [userText, setUserText] = useState('');
  const [aiText, setAiText] = useState('');
  const [hint, setHint] = useState('');
  const [notice, setNotice] = useState('');
  const [asrMeta, setAsrMeta] = useState('');
  const [handsFree, setHandsFree] = useState(true);
  const [speakOn, setSpeakOn] = useState(true);
  const [seconds, setSeconds] = useState(0);
  // 通话界面要"一屏装下"：高度按导航栏真实高度算（窄屏下导航会换行成两排，
  // 写死 calc(100vh-76px) 会把字幕顶到话筒下面去）
  const [availH, setAvailH] = useState<number | null>(null);
  const pageRef = useRef<HTMLDivElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // ——— 会被回调/定时器读取的可变状态，一律走 ref，避免闭包读到旧值 ———
  const dialectRef = useRef('普通话');
  const handsFreeRef = useRef(true);
  const speakOnRef = useRef(true);
  const endedRef = useRef(false);
  const mrRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const recStartRef = useRef(0);
  const vadTimerRef = useRef<number | null>(null);
  const vadCtxRef = useRef<AudioContext | null>(null);
  const relistenTimerRef = useRef<number | null>(null);
  const noticeTimerRef = useRef<number | null>(null);

  // 播放队列：逐句合成可能乱序返回，这里统一排队，保证一句接一句
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<string[]>([]);
  const playingRef = useRef(false);
  const waitersRef = useRef<Array<() => void>>([]);
  const speakChainRef = useRef<Promise<void>>(Promise.resolve());
  // 浏览器要求"用户点过才允许出声"。第一句话往往在点完 3~5 秒后才合成好，
  // 那时点击的临时授权已经过期，所以要趁点击当下把 <audio> 解锁一次。
  const unlockedRef = useRef(false);

  useEffect(() => setHydrated(true), []);

  useEffect(() => {
    handsFreeRef.current = handsFree;
  }, [handsFree]);
  useEffect(() => {
    speakOnRef.current = speakOn;
  }, [speakOn]);

  // 登录校验 + 读取当前方言
  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.push('/login');
      return;
    }
    if (user?.role === 'family') {
      router.push('/family');
      return;
    }
    settingsApi
      .dialect()
      .then((s) => {
        const name = s.enabled && s.active_dialect ? s.active_dialect : '普通话';
        setDialect(name);
        dialectRef.current = name;
        if (s.options?.length) {
          setOptions(s.options.map((o) => o.name));
          setVoiceMap(
            Object.fromEntries(s.options.map((o) => [o.name, o.has_voice !== false]))
          );
        }
      })
      .catch(() => undefined);
  }, [hydrated, accessToken, user, router]);

  // 通话计时
  useEffect(() => {
    if (!hydrated || !accessToken) return;
    const t = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [hydrated, accessToken]);

  // 量导航栏真实高度：字体放大/窄屏换行/登录后多出一排按钮都会改变它。
  // 只量一次或只靠 ResizeObserver 都不稳（水合后元素可能被替换），
  // 这里用一个很轻的定时轮询兜底，值不变就不触发重渲染。
  useEffect(() => {
    const measure = () => {
      const el = pageRef.current;
      if (!el) return;
      const top = el.getBoundingClientRect().top;
      // 根 layout 是 <main class="pb-8">，下面用 -mb-8 抵掉，这里只扣到视口底
      const next = Math.max(window.innerHeight - top, 400);
      setAvailH((prev) => (prev === null || Math.abs(prev - next) > 1 ? next : prev));
    };
    measure();
    const id = window.setInterval(measure, 400);
    window.addEventListener('resize', measure);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('resize', measure);
    };
  }, []);

  // 回复变长时，字幕区自动跟着滚
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [aiText, userText]);

  // ——— 播放 ———

  /** 造一段 0.05 秒的静音 wav，趁用户点击时播一下，把 <audio> 元素解锁。 */
  function silentWavUrl(): string {
    const sampleRate = 8000;
    const n = Math.floor(sampleRate * 0.05);
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const write = (offset: number, text: string) => {
      for (let i = 0; i < text.length; i += 1) v.setUint8(offset + i, text.charCodeAt(i));
    };
    write(0, 'RIFF');
    v.setUint32(4, 36 + n * 2, true);
    write(8, 'WAVE');
    write(12, 'fmt ');
    v.setUint32(16, 16, true);
    v.setUint16(20, 1, true);
    v.setUint16(22, 1, true);
    v.setUint32(24, sampleRate, true);
    v.setUint32(28, sampleRate * 2, true);
    v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    write(36, 'data');
    v.setUint32(40, n * 2, true);
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
  }

  function unlockAudio() {
    if (unlockedRef.current) return;
    const audio = audioRef.current;
    if (!audio) return;
    audio.volume = 0;
    audio.src = silentWavUrl();
    audio
      .play()
      .then(() => {
        unlockedRef.current = true;
        audio.pause();
        audio.volume = 1;
      })
      .catch(() => {
        audio.volume = 1;
      });
  }

  function playNext() {
    const url = queueRef.current.shift();
    const audio = audioRef.current;
    if (!url || !audio) {
      playingRef.current = false;
      setStage((s) => (s === 'speaking' ? 'idle' : s));
      const waiters = waitersRef.current.splice(0);
      waiters.forEach((fn) => fn());
      return;
    }
    playingRef.current = true;
    audio.src = url;
    audio.play().catch(() => playNext());
  }

  function enqueue(url: string) {
    queueRef.current.push(url);
    if (!playingRef.current) playNext();
  }

  function stopPlayback() {
    queueRef.current = [];
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute('src');
    }
    playingRef.current = false;
    const waiters = waitersRef.current.splice(0);
    waiters.forEach((fn) => fn());
  }

  function waitDrained(): Promise<void> {
    if (!playingRef.current && queueRef.current.length === 0) return Promise.resolve();
    return new Promise<void>((resolve) => {
      waitersRef.current.push(resolve);
    });
  }

  /** 逐句合成：串行链保证顺序，后面句子在前一句播放时就开始合成。 */
  function speakSentence(sentence: string) {
    const text = sentence.trim();
    if (!text || !speakOnRef.current) return;
    speakChainRef.current = speakChainRef.current.then(async () => {
      try {
        const r = await speechApi.tts(text);
        if (r.audio_url) enqueue(r.audio_url);
      } catch {
        // 单句失败不影响后面的句子
      }
    });
  }

  // ——— 录音与静音检测 ———

  function stopVad() {
    if (vadTimerRef.current) {
      window.clearInterval(vadTimerRef.current);
      vadTimerRef.current = null;
    }
    if (vadCtxRef.current) {
      vadCtxRef.current.close().catch(() => undefined);
      vadCtxRef.current = null;
    }
  }

  /**
   * 免提模式下的自动断句：靠音量判断"说完了没"。
   * 说话超过 0.36s 才开始计静音，连续 1.3s 没声音就自动结束这一段。
   */
  function startVad(stream: MediaStream) {
    try {
      const Ctx = window.AudioContext;
      const ctx = new Ctx();
      vadCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const buf = new Float32Array(analyser.fftSize);
      const startedAt = Date.now();
      let voiced = 0;
      let silentMs = 0;

      vadTimerRef.current = window.setInterval(() => {
        analyser.getFloatTimeDomainData(buf);
        let sum = 0;
        for (let i = 0; i < buf.length; i += 1) sum += buf[i] * buf[i];
        const rms = Math.sqrt(sum / buf.length);
        const elapsed = Date.now() - startedAt;
        if (elapsed < 400) return; // 开头一点杂音不算
        if (rms > 0.015) {
          voiced += 1;
          silentMs = 0;
        } else if (voiced > 2) {
          silentMs += 120;
        }
        if (voiced > 2 && silentMs >= 1300) stopRecording();
        // 一直没检测到人声：别傻等到 25 秒，3.5 秒就收，交给上层提示
        else if (voiced === 0 && elapsed > 3500) stopRecording();
        else if (elapsed > 25000) stopRecording();
      }, 120);
    } catch {
      // 拿不到音频分析能力就退化成手动点停
    }
  }

  function stopRecording() {
    const mr = mrRef.current;
    if (mr && mr.state !== 'inactive') mr.stop();
  }

  // 连续两次没听到内容就暂停免提，避免空录音反复打识别接口（也白花钱）
  const emptyStreakRef = useRef(0);

  function pauseHandsFree(reason: string) {
    setHandsFree(false);
    handsFreeRef.current = false;
    setHint(reason);
  }

  /** 这一轮没拿到内容：累计两次就停掉免提，别空转。 */
  function noteEmpty(msg: string, threshold = 2) {
    emptyStreakRef.current += 1;
    setStage('idle');
    if (emptyStreakRef.current >= threshold) {
      pauseHandsFree('没听到声音，免提已暂停。点话筒或「上传录音」继续。');
      return;
    }
    setHint(msg);
    if (handsFreeRef.current) scheduleRelisten(700);
  }

  async function startRecording(auto = false) {
    if (endedRef.current || mrRef.current) return;
    if (!auto) stopPlayback();
    stopVad();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (endedRef.current) {
        stream.getTracks().forEach((t) => t.stop());
        return;
      }
      streamRef.current = stream;
      const prefer = 'audio/webm;codecs=opus';
      const mr = MediaRecorder.isTypeSupported(prefer)
        ? new MediaRecorder(stream, { mimeType: prefer })
        : new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = () => {
        stopVad();
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        mrRef.current = null;
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        const secs = (Date.now() - recStartRef.current) / 1000;
        if (blob.size < 1200 || secs < 0.5) {
          // 录得太短连接口都不用打，不算一次失败，所以阈值放宽到 3 次
          noteEmpty('没听清，再说一次吧', 3);
          return;
        }
        void runTurn(blob, 'call.webm');
      };
      mrRef.current = mr;
      recStartRef.current = Date.now();
      mr.start(500);
      setHint('');
      setStage('listening');
      if (handsFreeRef.current) startVad(stream);
    } catch {
      setStage('idle');
      setHint('用不了麦克风。请允许浏览器使用麦克风，或者点「上传录音」。');
    }
  }

  function scheduleRelisten(delay = 800) {
    if (relistenTimerRef.current) window.clearTimeout(relistenTimerRef.current);
    relistenTimerRef.current = window.setTimeout(() => {
      if (!endedRef.current && handsFreeRef.current) void startRecording(true);
    }, delay);
  }

  function flashNotice(msg: string) {
    setNotice(msg);
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = window.setTimeout(() => setNotice(''), 2800);
  }

  async function setDialectTo(name: string) {
    dialectRef.current = name;
    setDialect(name);
    const noVoice = name !== '普通话' && voiceMap[name] === false;
    try {
      await settingsApi.setDialect(name !== '普通话', name);
      flashNotice(
        name === '普通话'
          ? '已切换成普通话'
          : noVoice
            ? `${name}暂时没有方言音色：回复会用方言词，但播报是普通话`
            : `已切换成${name}，AI 会用${name}回你、也用${name}念出来`
      );
    } catch {
      flashNotice('方言没保存成功，本次通话仍按选的方言走');
    }
  }

  /** 一轮完整对话：转写 → 流式回复 → 逐句播报 → 自动继续听 */
  async function runTurn(blob: Blob, filename: string) {
    if (endedRef.current) return;
    setStage('thinking');
    setHint('');
    setAsrMeta('');
    setAiText('');

    let text = '';
    try {
      const res = await speechApi.transcribe(blob, dialectRef.current, filename);
      text = (res.text || '').trim();
      if (res.elapsed_ms) {
        setAsrMeta(`${(res.elapsed_ms / 1000).toFixed(1)}s · ${res.model}`);
      }
    } catch (err) {
      setStage('idle');
      // 识别服务出错别自动重试：连续报错会把计费和时间都耗掉
      pauseHandsFree(friendly(err instanceof ApiError ? err.message : '语音识别失败'));
      return;
    }

    if (!text) {
      noteEmpty('没听清，再说一次吧');
      return;
    }
    if (endedRef.current) return;

    emptyStreakRef.current = 0;
    setUserText(text);
    speakChainRef.current = Promise.resolve();

    let acc = '';
    let spoken = 0;
    const PUNCT = '。！？!?；;\n';

    const flush = (final: boolean) => {
      const pending = acc.slice(spoken);
      if (!pending) return;
      let cut = 0;
      for (let i = 0; i < pending.length; i += 1) {
        if (PUNCT.includes(pending[i])) cut = i + 1;
      }
      if (final) cut = pending.length;
      if (cut === 0) return;
      const block = pending.slice(0, cut);
      spoken += cut;
      for (const piece of block.split(/(?<=[。！？!?；;\n])/)) {
        if (piece.trim()) speakSentence(piece);
      }
    };

    await new Promise<void>((resolve) => {
      chatApi
        .sendStream(text, {
          onDelta: (t) => {
            acc += t;
            setAiText(acc);
            setStage('speaking');
            flush(false);
          },
          onDone: (r) => {
            acc = r.reply || acc;
            setAiText(acc);
            flush(true);
            resolve();
          },
          onError: (msg) => {
            setHint(friendly(msg));
            resolve();
          },
        })
        .catch(() => resolve());
    });

    // 等最后一句合成完 + 播放完，再决定要不要继续听
    await speakChainRef.current;
    await waitDrained();
    if (endedRef.current) return;
    setStage('idle');
    if (handsFreeRef.current) scheduleRelisten(700);
  }

  const playSample = async (key: string, sampleDialect: string) => {
    if (endedRef.current || mrRef.current) return;
    unlockAudio();
    await setDialectTo(sampleDialect);
    try {
      const resp = await fetch(`/voice-samples/${key}.mp3`);
      if (!resp.ok) throw new Error('sample missing');
      const blob = await resp.blob();
      void runTurn(blob, `${key}.mp3`);
    } catch {
      setHint('示例录音加载失败');
    }
  };

  const hangUp = () => {
    endedRef.current = true;
    stopVad();
    if (relistenTimerRef.current) window.clearTimeout(relistenTimerRef.current);
    const mr = mrRef.current;
    if (mr && mr.state !== 'inactive') mr.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    stopPlayback();
    router.push('/');
  };

  // 离开页面一定要收掉麦克风，否则浏览器还亮着录音红点
  useEffect(() => {
    // 开发模式下 React 会把 effect 跑两遍（挂载→清理→再挂载），
    // 所以这里必须显式复位；只在清理里置 true 会让页面一进来就是"已挂断"。
    endedRef.current = false;
    const audio = audioRef.current;
    return () => {
      endedRef.current = true;
      stopVad();
      if (relistenTimerRef.current) window.clearTimeout(relistenTimerRef.current);
      if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
      const mr = mrRef.current;
      if (mr && mr.state !== 'inactive') mr.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
      audio?.pause();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleMic = useCallback(() => {
    unlockAudio();
    if (mrRef.current) stopRecording();
    else void startRecording(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!hydrated || !accessToken) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-xl text-gray-600">加载中...</p>
      </div>
    );
  }

  const busy = stage === 'thinking';
  const ringActive = stage === 'listening' || stage === 'speaking';

  return (
    <div
      ref={pageRef}
      className="text-white overflow-hidden -mb-8"
      style={{
        background:
          'radial-gradient(120% 85% at 50% 0%, #3d2a1b 0%, #241a12 45%, #14100c 100%)',
        height: availH ? `${availH}px` : 'calc(100vh - 76px)',
      }}
    >
      <div className="max-w-3xl mx-auto px-4 py-4 h-full flex flex-col overflow-hidden">
        {/* 顶部：挂断 / 计时 / 静音 */}
        <div className="shrink-0 flex items-center justify-between gap-3">
          <button
            type="button"
            onClick={hangUp}
            className="min-h-[48px] px-4 rounded-full bg-rose-600 hover:bg-rose-500 font-bold text-base"
          >
            ⬅ 挂断
          </button>
          <div className="text-center leading-tight">
            <p className="text-sm text-amber-200/70 tracking-widest">语音通话</p>
            <p className="text-xl font-mono tabular-nums">{mmss(seconds)}</p>
          </div>
          <button
            type="button"
            onClick={() => setSpeakOn((v) => !v)}
            aria-pressed={speakOn}
            className={`min-h-[48px] px-4 rounded-full text-base font-bold ${
              speakOn ? 'bg-white/15 hover:bg-white/25' : 'bg-white/5 text-white/50'
            }`}
            title={speakOn ? '关闭声音，只看文字' : '打开声音'}
          >
            {speakOn ? '🔊 有声' : '🔇 静音'}
          </button>
        </div>

        {/* 方言选择 */}
        <div className="mt-3 shrink-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-amber-200/60 mr-1">用哪种话说</span>
            {options.map((name) => (
              <button
                key={name}
                type="button"
                onClick={() => void setDialectTo(name)}
                aria-pressed={dialect === name}
                className={`min-h-[44px] px-4 rounded-full text-base font-medium transition ${
                  dialect === name
                    ? 'bg-amber-400 text-[#2a1c10] font-bold shadow-lg shadow-amber-500/20'
                    : 'bg-white/10 hover:bg-white/20 text-white/85'
                }`}
              >
                {name}
              </button>
            ))}
          </div>
          <p className="text-sm text-amber-200/50 mt-2">
            选好方言后：你说的话按方言识别，AI 用方言回你，也用方言念出来。
          </p>
        </div>

        {/* 中间：头像 + 状态 */}
        <div className="shrink-0 flex flex-col items-center justify-center gap-2 py-3">
          <div className="relative w-36 h-36 flex items-center justify-center">
            {ringActive && (
              <>
                <span className="absolute inset-0 rounded-full bg-amber-400/25 animate-ping" />
                <span className="absolute inset-4 rounded-full bg-amber-300/15" />
              </>
            )}
            <div
              className={`relative w-20 h-20 rounded-full flex items-center justify-center text-3xl shadow-2xl transition-transform ${
                stage === 'speaking' ? 'scale-105' : ''
              }`}
              style={{ background: 'linear-gradient(135deg,#FBBF24 0%,#F97316 100%)' }}
            >
              🌻
            </div>
          </div>
          <p className="text-lg text-white/85" aria-live="polite">
            {stage === 'idle' && handsFree ? '我在，接着说就行' : STAGE_TEXT[stage]}
          </p>
          {notice && <p className="text-base text-amber-300">{notice}</p>}
          {hint && <p className="text-base text-rose-300 text-center max-w-md">{hint}</p>}
        </div>

        {/* 字幕区 */}
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto pb-2">
          <div className="flex flex-col gap-3 pt-2">
          {userText && (
            <div className="self-end max-w-[85%] text-right">
              <p className="text-sm text-white/40 mb-1">
                你说{asrMeta ? ` · 识别 ${asrMeta}` : ''}
              </p>
              <p className="inline-block text-lg bg-white/10 rounded-2xl rounded-br-sm px-4 py-2 text-white/90">
                {userText}
              </p>
            </div>
          )}
          {aiText && (
            <div className="self-start max-w-[92%]">
              <p className="text-sm text-amber-200/50 mb-1">陪伴 AI</p>
              <p className="text-2xl leading-relaxed text-white whitespace-pre-wrap">{aiText}</p>
            </div>
          )}
          {!userText && !aiText && (
            <div className="bg-white/5 rounded-2xl p-4 border border-white/10">
              <p className="text-lg text-white/85 mb-1">不会说方言也能用</p>
              <p className="text-base text-white/60 leading-relaxed">
                点下面的示例录音，就能听到整段方言对话；也可以上传一段家里人说的方言音频。
              </p>
              <div className="flex flex-wrap gap-2 mt-4">
                {SAMPLES.map((s) => (
                  <button
                    key={s.key}
                    type="button"
                    onClick={() => void playSample(s.key, s.dialect)}
                    className="min-h-[48px] px-4 rounded-full bg-amber-400/90 hover:bg-amber-300 text-[#2a1c10] font-bold text-base"
                  >
                    ▶ {s.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          </div>
        </div>

        {/* 底部操作 */}
        <div className="shrink-0 flex items-center justify-between gap-4 pt-3 pb-1">
          <label
            className="min-h-[56px] min-w-[56px] flex-1 flex items-center justify-center gap-2 rounded-2xl bg-white/10 hover:bg-white/20 text-base font-medium cursor-pointer"
            title="上传一段录音（支持方言）"
          >
            <span className="text-xl">📁</span> 上传录音
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = '';
                if (f) void runTurn(f, f.name || 'upload.mp3');
              }}
            />
          </label>

          <button
            type="button"
            onClick={toggleMic}
            disabled={busy}
            className={`w-[88px] h-[88px] rounded-full flex items-center justify-center text-3xl font-bold shadow-2xl transition-all select-none ${
              busy
                ? 'bg-white/20 text-white/50'
                : stage === 'listening'
                  ? 'bg-rose-500 animate-pulse scale-105'
                  : 'bg-amber-400 text-[#2a1c10] hover:bg-amber-300'
            }`}
            aria-label={stage === 'listening' ? '结束说话' : '开始说话'}
          >
            {busy ? '⏳' : stage === 'listening' ? '⏹' : '🎤'}
          </button>

          <button
            type="button"
            onClick={() => setHandsFree((v) => !v)}
            aria-pressed={handsFree}
            className={`min-h-[56px] flex-1 rounded-2xl text-base font-medium ${
              handsFree ? 'bg-emerald-500/25 text-emerald-200 border border-emerald-400/40' : 'bg-white/10 hover:bg-white/20'
            }`}
            title="说完自动断句、AI 说完自动继续听"
          >
            {handsFree ? '🔁 免提：开' : '🔁 免提：关'}
          </button>
        </div>
      </div>

      <audio ref={audioRef} onEnded={playNext} onError={playNext} className="hidden" />
    </div>
  );
}

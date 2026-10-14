'use client';

import { useEffect, useRef, useState } from 'react';
import { speechApi } from '@/lib/api';

interface Props {
  text: string;
  label?: string;
  className?: string;
}

/**
 * 通用「朗读」按钮：点击后调用后端 TTS 合成并播放，可重复点击（播放/暂停）。
 * 老人友好：大按钮、大字号。
 */
export function SpeakButton({ text, label = '🔊 朗读', className = '' }: Props) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // 拿到音频地址后自动播放
  useEffect(() => {
    if (audioUrl) {
      audioRef.current?.play().catch(() => {});
    }
  }, [audioUrl]);

  const handleClick = async () => {
    // 已合成过：直接控制播放/暂停
    if (audioUrl) {
      if (playing) audioRef.current?.pause();
      else audioRef.current?.play().catch(() => {});
      return;
    }
    setLoading(true);
    try {
      const res = await speechApi.tts(text);
      if (res.audio_url) setAudioUrl(res.audio_url);
    } catch {
      // 静默失败，避免打扰老人
    } finally {
      setLoading(false);
    }
  };

  return (
    <span className="inline-flex items-center">
      <audio
        ref={audioRef}
        src={audioUrl ?? undefined}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
      <button
        type="button"
        onClick={handleClick}
        disabled={loading}
        className={`min-h-[48px] px-4 rounded-xl bg-warm-light hover:bg-warm-primary hover:text-white text-warm-primary font-medium disabled:opacity-50 ${className}`}
        aria-label={playing ? '暂停朗读' : label}
      >
        {loading ? '合成中…' : playing ? '⏸ 暂停' : label}
      </button>
    </span>
  );
}

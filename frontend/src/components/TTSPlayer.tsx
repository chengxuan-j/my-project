'use client';

import { useEffect, useRef, useState } from 'react';
import { speechApi } from '@/lib/api';

interface Props {
  text: string | null;
  autoPlay?: boolean;
}

/**
 * TTS 播放器：传入 text 后自动调后端合成并播放
 */
export function TTSPlayer({ text, autoPlay = true }: Props) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastTextRef = useRef<string | null>(null);

  useEffect(() => {
    if (!text || text === lastTextRef.current) return;
    lastTextRef.current = text;
    let cancelled = false;

    speechApi
      .tts(text)
      .then((res) => {
        if (cancelled) return;
        if (res.audio_url) {
          setAudioUrl(res.audio_url);
          if (autoPlay) {
            // 浏览器可能拦截自动播放，失败时静默
            setTimeout(() => {
              audioRef.current?.play().catch(() => {});
            }, 100);
          }
        }
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [text, autoPlay]);

  if (!audioUrl) return null;

  return (
    <div className="flex items-center gap-2">
      <audio
        ref={audioRef}
        src={audioUrl}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
      />
      <button
        onClick={() => {
          if (playing) audioRef.current?.pause();
          else audioRef.current?.play().catch(() => {});
        }}
        className="min-h-[48px] min-w-[48px] rounded-full bg-warm-light hover:bg-warm-primary hover:text-white text-warm-primary text-2xl flex items-center justify-center"
        title={playing ? '暂停' : '播放语音'}
        aria-label={playing ? '暂停语音' : '播放语音'}
      >
        {playing ? '⏸' : '🔊'}
      </button>
    </div>
  );
}

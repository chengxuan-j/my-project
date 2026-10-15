'use client';

import { useState } from 'react';
import type { MemoirStory } from '@/lib/api';
import { LargeButton } from './LargeButton';
import { SpeakButton } from './SpeakButton';
import { VoiceRecorder } from './VoiceRecorder';

interface Props {
  /** 待确认的回忆条目，一次只展示一条（克制，不一次堆给老人） */
  stories: MemoirStory[];
  onConfirm: (id: number, via: 'button' | 'voice') => void | Promise<void>;
  onDiscard: (id: number, via: 'button' | 'voice') => void | Promise<void>;
}

/** 把老人的口语回应归类：先判否定，再判肯定，都不中就是没听清 */
function parseVoiceAnswer(text: string): 'confirm' | 'discard' | null {
  const t = text.replace(/\s/g, '');
  if (!t) return null;
  if (/(先不|不用|不要|不好|不留|不记|别|算了|不要了)/.test(t)) return 'discard';
  if (/(留下|记下|留|好|对|是|可以|要|存)/.test(t)) return 'confirm';
  return null;
}

/**
 * 老人端留档确认卡（契约1：只有老人本人能点）。
 *
 * 极简：一句提示 + 摘要 + 两个大按钮，另提供语音确认与 TTS 播报。
 * 契约5：时间没把握时只标「时间存疑」，不提供任何纠正入口。
 */
export function StoryConfirmCard({ stories, onConfirm, onDiscard }: Props) {
  const [busy, setBusy] = useState(false);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [hint, setHint] = useState('');

  if (stories.length === 0) return null;
  const story = stories[0];
  const rest = stories.length - 1;

  const decide = async (via: 'button' | 'voice', action: 'confirm' | 'discard') => {
    if (busy) return;
    setBusy(true);
    setHint('');
    try {
      if (action === 'confirm') {
        await onConfirm(story.id, via);
      } else {
        await onDiscard(story.id, via);
      }
      setVoiceOpen(false);
    } finally {
      setBusy(false);
    }
  };

  const handleVoice = (text: string) => {
    const answer = parseVoiceAnswer(text);
    if (answer === 'confirm') {
      decide('voice', 'confirm');
    } else if (answer === 'discard') {
      decide('voice', 'discard');
    } else {
      setHint('没听清，您说「留下这段」或者「先不用」就行。');
    }
  };

  // 契约5：只标注存疑，不改口、不给纠正入口
  const timeUncertain = !!story.time_value && story.time_confidence < 0.5;

  return (
    <div className="bg-white border-2 border-warm-primary rounded-2xl p-4 mb-3">
      <div className="flex items-start justify-between gap-3 mb-2">
        <h3 className="font-bold text-warm-dark text-lg">📔 我记下来一段往事</h3>
        {rest > 0 && <span className="text-sm text-gray-500 mt-1">还有 {rest} 段</span>}
      </div>

      <p className="text-gray-900 text-lg leading-relaxed mb-2">
        {story.summary || story.title || '您刚说的这段往事'}
      </p>

      <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600 mb-3">
        {story.time_value && (
          <span>
            {story.time_inferred ? '约 ' : ''}
            {story.time_value}
          </span>
        )}
        {timeUncertain && (
          <span className="bg-amber-100 text-amber-800 rounded-lg px-2 py-0.5">时间存疑</span>
        )}
        {story.place && <span>· {story.place}</span>}
        {story.people.length > 0 && <span>· {story.people.join('、')}</span>}
        {story.era_tags.map((tag) => (
          <span key={tag} className="bg-warm-light text-warm-dark rounded-lg px-2 py-0.5">
            {tag}
          </span>
        ))}
      </div>

      <div className="mb-3">
        <SpeakButton text={story.speak_text} label="🔊 听我怎么记的" />
      </div>

      <p className="text-gray-700 mb-2">要留下这段吗？</p>

      <div className="flex flex-col sm:flex-row gap-2">
        <LargeButton
          variant="primary"
          size="xl"
          className="flex-1"
          disabled={busy}
          onClick={() => decide('button', 'confirm')}
        >
          ✅ 留下这段
        </LargeButton>
        <LargeButton
          variant="secondary"
          size="xl"
          className="flex-1"
          disabled={busy}
          onClick={() => decide('button', 'discard')}
        >
          ✋ 先不用
        </LargeButton>
      </div>

      <div className="mt-3">
        {!voiceOpen ? (
          <button
            type="button"
            onClick={() => {
              setVoiceOpen(true);
              setHint('');
            }}
            className="min-h-[48px] px-4 rounded-xl bg-warm-light text-warm-dark font-medium"
          >
            🎤 我来说
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <VoiceRecorder onRecognized={handleVoice} onError={(m) => setHint(m)} />
            <button
              type="button"
              onClick={() => setVoiceOpen(false)}
              className="min-h-[48px] px-4 rounded-xl bg-warm-light text-gray-700"
            >
              收起
            </button>
          </div>
        )}
      </div>

      {hint && <p className="text-sm text-amber-700 mt-2">{hint}</p>}
    </div>
  );
}

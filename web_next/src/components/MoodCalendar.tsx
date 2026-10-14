'use client';

import { useEffect, useState } from 'react';
import { emotionApi, EmotionTrendDay } from '@/lib/api';
import { EMOTION_LABEL } from '@/components/EmotionChart';
import { SpeakButton } from '@/components/SpeakButton';

const EMOTION_EMOJI: Record<string, string> = {
  happy: '😊',
  sad: '😢',
  anxious: '😟',
  lonely: '😔',
  calm: '😌',
  angry: '😠',
  neutral: '😐',
  bored: '😪',
  tired: '😩',
  nostalgic: '🥹',
  grateful: '🥰',
  worried: '😟',
};

// 暖色=好心情，冷色=低落，灰=无记录
const EMOTION_TONE: Record<string, string> = {
  happy: 'bg-green-100 border-green-300',
  calm: 'bg-teal-100 border-teal-300',
  grateful: 'bg-emerald-100 border-emerald-300',
  nostalgic: 'bg-pink-100 border-pink-300',
  neutral: 'bg-gray-100 border-gray-300',
  bored: 'bg-purple-100 border-purple-300',
  tired: 'bg-slate-100 border-slate-300',
  worried: 'bg-orange-100 border-orange-300',
  anxious: 'bg-amber-100 border-amber-300',
  lonely: 'bg-violet-100 border-violet-300',
  sad: 'bg-blue-100 border-blue-300',
  angry: 'bg-red-100 border-red-300',
};

const POSITIVE = new Set(['happy', 'calm', 'grateful', 'nostalgic']);
const NEGATIVE = new Set(['sad', 'lonely', 'anxious', 'worried', 'angry']);

function dateKey(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

interface Cell {
  date: string;
  weekday: string;
  day: EmotionTrendDay | undefined;
}

export function MoodCalendar() {
  const [trend, setTrend] = useState<EmotionTrendDay[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    emotionApi
      .trend(14)
      .then((t) => setTrend(Array.isArray(t) ? t : []))
      .catch(() => setTrend([]))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6 text-gray-600">
        📅 正在整理您的心情...
      </section>
    );
  }

  const byDate = new Map(trend.map((d) => [d.date, d]));
  const today = new Date();
  const cells: Cell[] = [];
  for (let i = 13; i >= 0; i--) {
    const dt = new Date(today);
    dt.setDate(today.getDate() - i);
    const key = dateKey(dt);
    cells.push({
      date: key,
      weekday: ['日', '一', '二', '三', '四', '五', '六'][dt.getDay()],
      day: byDate.get(key),
    });
  }

  const daysWithData = cells.filter((c) => c.day);
  const recent7 = cells.slice(-7).filter((c) => c.day);
  const happyDays = recent7.filter((c) => POSITIVE.has(c.day!.dominant_emotion)).length;
  const sadDays = recent7.filter((c) => NEGATIVE.has(c.day!.dominant_emotion)).length;

  const talk =
    daysWithData.length === 0
      ? '这几天还没有心情记录，和我聊聊今天过得怎么样吧 🌻'
      : sadDays >= 4
        ? `这一周您有 ${sadDays} 天心情不太好，我一直陪着您，愿意的话跟我说说心里话。`
        : happyDays >= 4
          ? `这一周您有 ${happyDays} 天挺开心的，看到您高兴，我也跟着开心！`
          : `这一周您来过 ${recent7.length} 天，心情有起有落，都是再平常不过的好日子。`;

  return (
    <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-1">📅 我的心情日历</h2>
      <p className="text-sm text-gray-500 mb-4">最近两周，每天的心情一目了然</p>

      <div className="grid grid-cols-7 gap-2">
        {cells.map((c) => {
          const emo = c.day?.dominant_emotion;
          const tone = emo ? EMOTION_TONE[emo] || 'bg-gray-100 border-gray-300' : 'bg-gray-50 border-dashed border-gray-200';
          return (
            <div
              key={c.date}
              className={`rounded-xl border-2 ${tone} aspect-square flex flex-col items-center justify-center p-1`}
              title={
                c.day
                  ? `${c.date}：${EMOTION_LABEL[emo!] || emo}（${c.day.record_count} 次）`
                  : `${c.date}：无记录`
              }
            >
              <span className="text-xs text-gray-500">周{c.weekday}</span>
              <span className="text-2xl leading-none my-0.5">
                {emo ? EMOTION_EMOJI[emo] || '💭' : '·'}
              </span>
              <span className="text-[10px] text-gray-500">
                {c.day ? EMOTION_LABEL[emo!] || emo : ''}
              </span>
            </div>
          );
        })}
      </div>

      <div className="mt-4 bg-warm-light/50 rounded-xl px-4 py-3 flex items-center justify-between gap-3 flex-wrap">
        <p className="text-gray-800 flex-1 min-w-[200px]">🌻 {talk}</p>
        <SpeakButton text={talk} label="🔊 读给我听" />
      </div>
    </section>
  );
}

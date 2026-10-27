'use client';

import type { RiverStage } from '@/lib/api';

const TONE_STYLE: Record<string, string> = {
  amber: 'bg-amber-50 border-amber-300 text-amber-900',
  blue: 'bg-sky-50 border-sky-300 text-sky-900',
  gray: 'bg-gray-50 border-gray-300 text-gray-700',
};

/** 人生时光河：回忆按人生阶段汇成一条河，颜色是当时的情绪基调。 */
export function LifeRiver({ stages, total }: { stages: RiverStage[]; total: number }) {
  if (total === 0) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        这条河还空着。多和 AI 聊聊过去的事，回忆就会住进这里 🌱
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900">🌊 我的人生河</h3>
      <p className="text-sm text-gray-500 mt-1 mb-4">
        你的回忆按年纪汇成这条河。暖色是温暖的往事，蓝色是辛酸的往事，灰色是平平淡淡的日常。
      </p>

      {/* 河面：贯穿各阶段的波浪线 */}
      <svg viewBox="0 0 680 24" className="w-full h-6 mb-2" preserveAspectRatio="none">
        <path
          d="M0 12 Q 85 2, 170 12 T 340 12 T 510 12 T 680 12"
          fill="none"
          stroke="#F5C26B"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {stages.map((stage) => (
          <div key={stage.label} className="flex flex-col gap-2">
            <p className="text-xs font-bold text-center text-warm-dark bg-warm-light rounded-full py-1">
              {stage.label}
            </p>
            {stage.stories.length === 0 ? (
              <div className="border-2 border-dashed border-warm-light rounded-xl h-20 flex items-center justify-center text-xs text-gray-300">
                虚位以待
              </div>
            ) : (
              stage.stories.map((s) => (
                <div
                  key={s.id}
                  className={`rounded-xl border-2 p-2.5 ${TONE_STYLE[s.tone_color] || TONE_STYLE.gray}`}
                  title={s.summary}
                >
                  <p className="font-bold text-sm leading-snug">{s.title}</p>
                  <div className="flex items-center gap-1.5 mt-1.5 text-xs">
                    <span className="bg-white/70 rounded-full px-1.5 py-0.5">{s.emotion_tone}</span>
                    {s.time_value && <span className="opacity-70">{s.time_value}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        ))}
      </div>

      <p className="text-xs text-gray-400 mt-3">
        这些回忆只给你自己看。想给家人看的，可以在「回忆录」里单独设置。
      </p>
    </div>
  );
}

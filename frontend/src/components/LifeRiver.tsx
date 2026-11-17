'use client';

import Link from 'next/link';
import type { RiverStage } from '@/lib/api';

const TONE_STYLE: Record<string, string> = {
  amber: 'bg-amber-50 border-amber-300 text-amber-900',
  blue: 'bg-sky-50 border-sky-300 text-sky-900',
  gray: 'bg-gray-50 border-gray-300 text-gray-700',
};

/**
 * 人生河：只看**轮廓**。
 *
 * 完整故事在《人生之书》里按章节阅读，原始素材在「回忆录」里管理；
 * 这里如果再把每段的标题/情绪铺一遍，三个页面就会长得一模一样。
 * 所以这里只回答一个问题：哪段岁月留下了几段回忆。
 */
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
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h3 className="text-lg font-bold text-gray-900">🌊 人生河 · 阶段概览</h3>
        <Link href="/book" className="text-sm font-semibold text-warm-dark hover:underline">
          去《人生之书》读完整故事 →
        </Link>
      </div>
      <p className="text-sm text-gray-500 mt-1 mb-4">
        这里只看轮廓：哪段岁月留下了几段回忆。只统计确认留档的故事，原文去书里读。
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
        {stages.map((stage) => {
          const count = stage.stories.length;
          const titles = stage.stories.map((s) => s.title).filter(Boolean);
          const tone = stage.stories[0]?.tone_color || 'gray';
          return (
            <div key={stage.label} className="flex flex-col gap-2">
              <p className="text-xs font-bold text-center text-warm-dark bg-warm-light rounded-full py-1">
                {stage.label}
              </p>
              {count === 0 ? (
                <div className="border-2 border-dashed border-warm-light rounded-xl h-20 flex items-center justify-center text-xs text-gray-300">
                  虚位以待
                </div>
              ) : (
                <div className={`rounded-xl border-2 p-2.5 ${TONE_STYLE[tone] || TONE_STYLE.gray}`}>
                  <p className="text-xs font-semibold opacity-70">{count} 段回忆</p>
                  <p className="mt-1 text-sm font-bold leading-snug break-words">
                    {titles.slice(0, 2).join('、')}
                    {titles.length > 2 ? ' 等' : ''}
                  </p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <p className="text-xs text-gray-400 mt-3">
        这些回忆只给你自己看。想给家人看的，可以在「回忆录」里单独设置。
      </p>
    </div>
  );
}

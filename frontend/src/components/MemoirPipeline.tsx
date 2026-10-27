'use client';

import type { MemoirPipelineData } from '@/lib/api';

const STAGE_COLORS = [
  'bg-blue-50 border-blue-200',
  'bg-violet-50 border-violet-200',
  'bg-amber-50 border-amber-200',
  'bg-emerald-50 border-emerald-200',
];

export function MemoirPipeline({ pipeline }: { pipeline: MemoirPipelineData | null }) {
  if (!pipeline || pipeline.stages.length === 0) return null;

  const hasAny = pipeline.stages.some((s) => s.items.some((i) => i.count > 0));

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900">📖 回忆录是怎么长出来的</h3>
      <p className="text-sm text-gray-500 mt-1 mb-4">
        从一句闲聊到一条留档的回忆，中间隔着这四步。每一步都由老人主导，系统只负责整理。
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {pipeline.stages.map((stage, i) => (
          <div key={stage.key} className="relative">
            <div className={`rounded-xl border-2 p-3 h-full ${STAGE_COLORS[i % STAGE_COLORS.length]}`}>
              <p className="font-bold text-gray-900 text-sm">{stage.label}</p>
              <p className="text-xs text-gray-500 mt-1 leading-relaxed">{stage.detail}</p>
              <div className="flex flex-wrap gap-1 mt-2">
                {stage.items.map((item) => (
                  <span
                    key={item.label}
                    className="text-xs bg-white border border-warm-light rounded-full px-2 py-0.5 text-gray-700"
                  >
                    {item.label} <strong className="text-gray-900">{item.count}</strong>
                  </span>
                ))}
              </div>
            </div>
            {i < pipeline.stages.length - 1 && (
              <span className="hidden lg:block absolute top-1/2 -right-3 -translate-y-1/2 text-gray-400 font-bold">
                →
              </span>
            )}
          </div>
        ))}
      </div>

      {pipeline.era_tags.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mt-4">
          <span className="text-sm text-gray-500">已留档回忆覆盖的年代：</span>
          {pipeline.era_tags.map((t) => (
            <span key={t.label} className="text-xs bg-warm-light rounded-full px-2 py-1 text-gray-700">
              {t.label} × {t.count}
            </span>
          ))}
        </div>
      )}

      <p className="mt-3 text-xs text-gray-400">
        🔒 {pipeline.privacy_note}
      </p>
      {!hasAny && (
        <p className="mt-2 text-sm text-gray-500">老人还没有留下可分享的回忆，先从聊天开始吧。</p>
      )}
    </div>
  );
}

'use client';

import type { CareSignals } from '@/lib/api';

const LEVEL_STYLE: Record<string, { bar: string; text: string; chip: string }> = {
  high: { bar: 'bg-rose-500', text: 'text-rose-700', chip: 'bg-rose-50 border-rose-200' },
  medium: { bar: 'bg-amber-500', text: 'text-amber-700', chip: 'bg-amber-50 border-amber-200' },
  low: { bar: 'bg-yellow-400', text: 'text-yellow-700', chip: 'bg-yellow-50 border-yellow-200' },
  none: { bar: 'bg-gray-200', text: 'text-gray-400', chip: 'bg-gray-50 border-gray-200' },
};

/** 陪伴需求信号面板：回答"老人最近在要什么"（只看标注，不看内容）。 */
export function CareSignalPanel({ signals }: { signals: CareSignals | null }) {
  if (!signals) return null;

  const active = signals.signals.filter((s) => s.count > 0);

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <div className="flex items-center justify-between mb-1">
        <h3 className="text-lg font-bold text-gray-900">💡 陪伴需求信号</h3>
        <span className="text-xs text-gray-400">近 {signals.window_days} 天</span>
      </div>
      <p className="text-sm text-gray-500 mb-4">
        从聊天话题和意图里读出老人可能需要什么。只统计话题词，不涉及聊天内容。
      </p>

      {active.length === 0 ? (
        <p className="text-gray-500 text-sm">
          近 {signals.window_days} 天没有检出明显需求信号，保持日常陪伴就好。
          {signals.scene_summary.silence_checkin > 0 && '（期间系统主动问安过几次）'}
        </p>
      ) : (
        <div className="space-y-3">
          {active.map((s) => {
            const st = LEVEL_STYLE[s.level] ?? LEVEL_STYLE.none;
            const deltaText =
              s.delta > 0 ? `↑ 比上周多 ${s.delta}` : s.delta < 0 ? `↓ 比上周少 ${-s.delta}` : '与上周持平';
            return (
              <div key={s.key} className={`rounded-xl border p-3 ${st.chip}`}>
                <div className="flex items-center gap-2">
                  <span className="text-xl">{s.icon}</span>
                  <span className="font-bold text-gray-900">{s.label}</span>
                  <span className={`ml-auto font-bold ${st.text}`}>{s.count} 次</span>
                  <span className="text-xs text-gray-500">{deltaText}</span>
                </div>
                <div className="h-1.5 bg-white/70 rounded-full mt-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full ${st.bar}`}
                    style={{ width: `${Math.min(s.count / 8, 1) * 100}%` }}
                  />
                </div>
                <p className="text-sm text-gray-600 mt-1.5">👉 {s.hint}</p>
              </div>
            );
          })}
        </div>
      )}

      {(signals.top_topics.length > 0 || signals.scene_summary.total > 0) && (
        <div className="flex flex-wrap items-center gap-2 mt-4 text-sm text-gray-600">
          <span className="text-gray-500">最近常聊：</span>
          {signals.top_topics.map((t) => (
            <span key={t.label} className="bg-warm-light rounded-full px-2 py-1 text-xs text-gray-700">
              {t.label} × {t.count}
            </span>
          ))}
          <span className="text-xs text-gray-400 ml-auto">{signals.silence_note}</span>
        </div>
      )}
    </div>
  );
}

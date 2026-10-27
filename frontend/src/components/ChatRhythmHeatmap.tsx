'use client';

import type { ChatRhythm } from '@/lib/api';

const HOUR_TICKS = [0, 3, 6, 9, 12, 15, 18, 21];

/** 热力图色阶：浅暖 → 深琥珀（与 warm 主题一致；0 值用最浅的暖白） */
function heatColor(count: number, max: number): string {
  if (count <= 0) return '#FBF3E4';
  const ratio = max > 0 ? count / max : 0;
  if (ratio >= 0.66) return '#B45309';
  if (ratio >= 0.33) return '#D97706';
  return '#F5C26B';
}

function hourText(h: number): string {
  return h < 10 ? `0${h}` : `${h}`;
}

export function ChatRhythmHeatmap({ rhythm }: { rhythm: ChatRhythm | null }) {
  if (!rhythm || rhythm.total_rounds === 0) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        近 {rhythm?.days ?? 28} 天还没有聊天记录，开始对话后这里会出现老人的作息节律 🕐
      </div>
    );
  }

  const max = Math.max(...rhythm.matrix.flat(), 1);
  const peak = rhythm.peak;
  const peakText = peak
    ? `${rhythm.weekday_labels[peak.weekday]} ${hourText(peak.hour)} 点（${peak.count} 轮）`
    : '—';
  const nightPct = Math.round(rhythm.night_ratio * 100);

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900">🕐 对话节律</h3>
      <p className="text-sm text-gray-500 mt-1 mb-4">
        近 {rhythm.days} 天老人每个时段聊了多少轮（颜色越深聊得越多）。只看时间，不看内容。
      </p>

      {/* 7 行 × 24 列 */}
      <div className="space-y-[3px]">
        {rhythm.matrix.map((row, wd) => (
          <div key={wd} className="grid grid-cols-[36px_repeat(24,minmax(0,1fr))] gap-[3px] items-center">
            <span className="text-xs text-gray-500 text-right pr-1">
              {rhythm.weekday_labels[wd]}
            </span>
            {row.map((count, hour) => (
              <div
                key={hour}
                className="h-[18px] rounded-[3px] transition-colors"
                style={{ backgroundColor: heatColor(count, max) }}
                title={`${rhythm.weekday_labels[wd]} ${hourText(hour)} 点 · ${count} 轮`}
              />
            ))}
          </div>
        ))}
      </div>

      {/* 小时轴 */}
      <div className="grid grid-cols-[36px_repeat(24,minmax(0,1fr))] gap-[3px] mt-1">
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} className="text-[10px] text-gray-400 text-center">
            {HOUR_TICKS.includes(h) ? h : ''}
          </span>
        ))}
      </div>

      {/* 图例 + 统计 */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 mt-4 text-sm text-gray-600">
        <span className="flex items-center gap-1">
          少
          {['#FBF3E4', '#F5C26B', '#D97706', '#B45309'].map((c) => (
            <span key={c} className="inline-block w-3 h-3 rounded-[2px]" style={{ backgroundColor: c }} />
          ))}
          多
        </span>
        <span>共 <strong className="text-gray-900">{rhythm.total_rounds}</strong> 轮</span>
        <span><strong className="text-gray-900">{rhythm.active_days}</strong> 天聊过</span>
        <span>最常聊：<strong className="text-gray-900">{peakText}</strong></span>
      </div>

      {nightPct >= 15 && (
        <p className="mt-3 text-sm bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 text-amber-800">
          🌙 夜间（22 点 - 早 6 点）聊天占 {nightPct}%，可以留意一下老人的睡眠情况。
        </p>
      )}
    </div>
  );
}

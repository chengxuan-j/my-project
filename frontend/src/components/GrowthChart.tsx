'use client';

import type { GrowthMonth } from '@/lib/api';

const TYPE_LABELS: Record<string, string> = {
  life_experience: '人生经历',
  family: '家人',
  preference: '喜好',
  interest: '兴趣',
  general: '日常',
  health: '健康',
  place: '地方',
};

const TYPE_COLORS: Record<string, string> = {
  life_experience: '#B45309',
  family: '#D97706',
  preference: '#F59E0B',
  interest: '#FBBF24',
  general: '#D6D3CD',
  health: '#0EA5E9',
  place: '#84CC16',
};

/** AI 陪伴成长：近 6 个月记忆积累（堆叠柱，按记忆类型着色）。 */
export function GrowthChart({
  months,
  total,
  daysTogether,
  thisMonth,
}: {
  months: GrowthMonth[];
  total: number;
  daysTogether: number;
  thisMonth: number;
}) {
  const max = Math.max(...months.map((m) => m.count), 1);
  const legend = Array.from(
    new Set(months.flatMap((m) => Object.keys(m.by_type || {})))
  );

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-2 mb-4">
        <div>
          <p className="text-sm text-gray-500">AI 已经记得关于你的</p>
          <p className="text-3xl font-bold text-warm-primary">{total}<span className="text-base ml-1">件事</span></p>
        </div>
        <div>
          <p className="text-sm text-gray-500">互相陪伴</p>
          <p className="text-3xl font-bold text-warm-primary">{daysTogether}<span className="text-base ml-1">天</span></p>
        </div>
        <div>
          <p className="text-sm text-gray-500">这个月新记住</p>
          <p className="text-3xl font-bold text-warm-primary">{thisMonth}<span className="text-base ml-1">条</span></p>
        </div>
      </div>

      <div className="flex items-end gap-2 h-32">
        {months.map((m) => (
          <div key={m.month} className="flex-1 flex flex-col items-center gap-1">
            <span className="text-xs text-gray-500">{m.count > 0 ? m.count : ''}</span>
            <div className="w-full flex flex-col-reverse rounded-t-lg overflow-hidden" style={{ height: `${(m.count / max) * 100}%`, minHeight: m.count > 0 ? 4 : 2, backgroundColor: m.count === 0 ? '#F1EFE8' : undefined }}>
              {Object.entries(m.by_type || {}).map(([type, n]) => (
                <div
                  key={type}
                  style={{ height: `${(n / Math.max(m.count, 1)) * 100}%`, backgroundColor: TYPE_COLORS[type] || '#D6D3CD' }}
                  title={`${TYPE_LABELS[type] || type} ${n} 条`}
                />
              ))}
            </div>
            <span className="text-[10px] text-gray-400">{m.month.slice(5)}月</span>
          </div>
        ))}
      </div>

      {legend.length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 mt-3">
          {legend.map((t) => (
            <span key={t} className="flex items-center gap-1 text-xs text-gray-500">
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: TYPE_COLORS[t] || '#D6D3CD' }} />
              {TYPE_LABELS[t] || t}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

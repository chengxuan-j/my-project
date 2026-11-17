'use client';

import type { CareIndex } from '@/lib/api';

const LEVEL_STYLE: Record<
  CareIndex['level'],
  { stroke: string; text: string; chip: string; label: string }
> = {
  good: {
    stroke: '#059669',
    text: 'text-success',
    chip: 'bg-success-soft border-hairline text-success',
    label: '状态不错',
  },
  watch: {
    stroke: '#D97706',
    text: 'text-warning',
    chip: 'bg-warning-soft border-hairline text-warning',
    label: '需要关注',
  },
  risk: {
    stroke: '#DC2626',
    text: 'text-danger',
    chip: 'bg-danger-soft border-hairline text-danger',
    label: '建议尽快联系',
  },
};

const RADIUS = 52;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

export function CareIndexGauge({ care }: { care: CareIndex | null }) {
  if (!care) return null;

  const style = LEVEL_STYLE[care.level] ?? LEVEL_STYLE.watch;
  const ratio = Math.max(0, Math.min(care.score, 100)) / 100;

  return (
    <div className="bg-card rounded-card p-5 shadow-card border border-hairline">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-lg font-bold text-ink">💗 关怀指数</h3>
        <span className={`text-xs font-bold border rounded-full px-3 py-1 ${style.chip}`}>
          {style.label}
        </span>
      </div>

      <div className="flex flex-col sm:flex-row items-center gap-6">
        {/* 环形仪表盘 */}
        <div className="relative shrink-0">
          <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label={`关怀指数 ${care.score} 分`}>
            <title>关怀指数 {care.score} 分</title>
            <circle cx="70" cy="70" r={RADIUS} fill="none" stroke="#F1EFE8" strokeWidth="12" />
            <circle
              cx="70"
              cy="70"
              r={RADIUS}
              fill="none"
              stroke={style.stroke}
              strokeWidth="12"
              strokeLinecap="round"
              strokeDasharray={`${CIRCUMFERENCE * ratio} ${CIRCUMFERENCE}`}
              transform="rotate(-90 70 70)"
            />
            <text x="70" y="66" textAnchor="middle" dominantBaseline="central" fontSize="34" fontWeight={500} fill="#2C2C2A">
              {care.score}
            </text>
            <text x="70" y="92" textAnchor="middle" dominantBaseline="central" fontSize="12" fill="#5F5E5A">
              满分 100
            </text>
          </svg>
        </div>

        {/* 因子分解 */}
        <div className="flex-1 w-full space-y-3">
          {care.factors.map((f) => (
            <div key={f.key}>
              <div className="flex items-baseline justify-between text-sm">
                <span className="font-medium text-ink">
                  {f.label}
                  <span className="ml-2 text-faint text-xs">{f.detail}</span>
                </span>
                <span className="text-ink font-bold shrink-0 ml-2">
                  {f.score}/{f.max}
                </span>
              </div>
              <div className="h-2 bg-primary-soft rounded-full mt-1 overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${f.max > 0 ? (f.score / f.max) * 100 : 0}%`,
                    backgroundColor: style.stroke,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      <p className="mt-4 text-sm bg-primary-softer rounded-btn px-3 py-2 text-ink">
        💡 {care.advice}
      </p>
      <p className="mt-2 text-xs text-faint">
        指数由情绪、聊天活跃、沉默风险、家庭联结四部分合成，只使用统计信息，不含对话内容。
      </p>
    </div>
  );
}

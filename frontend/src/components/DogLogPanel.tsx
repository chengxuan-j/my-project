'use client';

import type { DogLog } from '@/lib/api';

/** 机器狗陪伴日志：小狗跑了几趟、谁最常带话、老人看了没有。 */
export function DogLogPanel({ log }: { log: DogLog | null }) {
  if (!log || log.total_runs === 0) {
    return (
      <div className="mt-4 border-2 border-dashed border-warm-light rounded-2xl p-4 text-center text-sm text-gray-500">
        小狗还没跑过腿。在上面写一句话，让它捎给老人吧 🐶
      </div>
    );
  }

  const readPct = Math.round(log.read_rate * 100);

  return (
    <div className="mt-4 bg-white rounded-2xl border border-warm-light p-4 shadow-sm">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-gray-900">🐕 小狗跑腿记录</h3>
        <span className="text-xs text-gray-400">
          最近一次 {log.last_run_at ? new Date(log.last_run_at).toLocaleDateString('zh-CN') : '—'}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="bg-amber-50 rounded-xl p-2.5 text-center">
          <p className="text-xl font-bold text-amber-700">{log.total_runs}</p>
          <p className="text-xs text-gray-500">累计跑腿</p>
        </div>
        <div className="bg-emerald-50 rounded-xl p-2.5 text-center">
          <p className="text-xl font-bold text-emerald-700">{readPct}%</p>
          <p className="text-xs text-gray-500">老人已看到</p>
        </div>
        <div className="bg-rose-50 rounded-xl p-2.5 text-center">
          <p className="text-xl font-bold text-rose-700">{log.unread_count}</p>
          <p className="text-xs text-gray-500">还没看到</p>
        </div>
      </div>

      {log.top_relations.length > 0 && (
        <p className="text-sm text-gray-600 mb-3">
          最常捎话的是：
          {log.top_relations.map((r) => (
            <span key={r.label} className="ml-1 text-gray-900 font-medium">
              {r.label}（{r.count}）
            </span>
          ))}
        </p>
      )}

      <ul className="space-y-2">
        {log.records.map((r) => (
          <li key={r.id} className="flex items-start gap-2 bg-warm-light/40 rounded-xl px-3 py-2">
            <span className="text-lg leading-none mt-0.5">🐶</span>
            <div className="flex-1 min-w-0">
              <p className="text-gray-900 text-sm">{r.content}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {new Date(r.created_at).toLocaleString('zh-CN')}
                {r.is_read
                  ? r.reaction
                    ? ` · 老人看了，回应 ${r.reaction}`
                    : ' · 老人已经看到'
                  : ' · 老人还没看到'}
              </p>
            </div>
          </li>
        ))}
      </ul>
      {log.total_runs > log.records.length && (
        <p className="text-xs text-gray-400 mt-2 text-center">
          仅显示最近 {log.records.length} 条，共 {log.total_runs} 条
        </p>
      )}
    </div>
  );
}

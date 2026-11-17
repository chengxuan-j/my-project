'use client';

import type { Portrait } from '@/lib/api';

/** 「AI 眼中的你」：老人端画像卡，语气像老朋友聊天，不像数据报表。 */
export function PortraitCard({ portrait }: { portrait: Portrait | null }) {
  if (!portrait) return null;

  const name = portrait.elderly_name || '你';
  const hasAny =
    portrait.interests.length > 0 ||
    portrait.top_persons.length > 0 ||
    portrait.top_topics.length > 0;

  return (
    <div className="bg-card rounded-card p-5 shadow-card border border-hairline">
      <h3 className="text-lg font-bold text-ink">🪞 AI 眼中的{name}</h3>
      <p className="text-sm text-muted mt-1 mb-4">
        相处了 {portrait.days_together} 天，我记得的这些事，你看准不准。
      </p>

      {!hasAny ? (
        <p className="text-muted text-sm">还在慢慢了解你，多聊几天就有话说了。</p>
      ) : (
        <div className="space-y-4">
          {portrait.interests.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink mb-1.5">你喜欢的</p>
              <div className="flex flex-wrap gap-2">
                {portrait.interests.map((w) => (
                  <span key={w} className="bg-warning-soft border border-hairline rounded-full px-3 py-1 text-sm text-warning">
                    {w}
                  </span>
                ))}
              </div>
            </div>
          )}

          {portrait.top_persons.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink mb-1.5">你常提起的人</p>
              <div className="flex flex-wrap gap-2">
                {portrait.top_persons.map((p) => (
                  <span key={p.label} className="bg-accent-soft border border-hairline rounded-full px-3 py-1 text-sm text-accent">
                    {p.label}
                    <span className="ml-1 text-muted text-xs">{p.count} 次</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {portrait.top_topics.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink mb-1.5">你爱聊的话题</p>
              <div className="flex flex-wrap gap-2">
                {portrait.top_topics.map((t) => (
                  <span key={t.label} className="bg-primary-soft rounded-full px-3 py-1 text-sm text-ink">
                    {t.label}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="bg-success-soft border border-hairline rounded-btn px-4 py-3 text-sm text-success">
            🕐 {portrait.habit_text}
          </div>

          {portrait.taboos.length > 0 && (
            <p className="text-xs text-faint">
              有些话题你不想聊，我都记着，不会多问。
            </p>
          )}
        </div>
      )}

      <p className="text-xs text-faint mt-4">
        这张卡片只有你自己看得到。哪里说得不对，聊天时告诉我，我会改。
      </p>
    </div>
  );
}

'use client';

import { ReactNode, useMemo, useState } from 'react';
import type { EraAxisGroup, MemoirTimeline, StoryMediaItem, TimelineStory } from '@/lib/api';
import { StoryPhotoStrip } from '@/components/StoryPhoto';

/** 时间存疑的阈值：与后端 INFERRED_CONFIDENCE_CAP 保持一致。 */
const LOW_CONFIDENCE = 0.5;

function isUnsure(story: TimelineStory): boolean {
  return story.time_inferred || story.time_confidence < LOW_CONFIDENCE;
}

function StoryBlock({
  story,
  viewer,
  onDeleteMedia,
  renderExtra,
}: {
  story: TimelineStory;
  viewer: 'elderly' | 'family';
  onDeleteMedia?: (m: StoryMediaItem) => void;
  renderExtra?: (story: TimelineStory) => ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const unsure = isUnsure(story);

  return (
    <li className="bg-white rounded-xl border border-amber-200 p-4 hc-invert">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-bold text-warm-dark bg-warm-light rounded-lg px-2 py-1">
            {story.display_time || '时间不详'}
          </span>
          {/* 契约5：时间有偏差只做标注，不提供任何「纠正」入口 */}
          {unsure && (
            <span
              className="text-sm text-gray-500 border border-gray-300 rounded-lg px-2 py-0.5"
              title={
                story.inferred_from
                  ? `由画像推断：${story.inferred_from}`
                  : '老人没有说死时间'
              }
            >
              时间存疑
            </span>
          )}
        </div>
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="min-h-[40px] px-3 rounded-lg text-warm-primary hover:bg-warm-light text-base"
        >
          {open ? '收起' : '看看'}
        </button>
      </div>

      <h4 className="mt-2 text-lg font-bold text-gray-800">{story.title || '一段回忆'}</h4>
      <p
        className={`text-gray-700 mt-1 leading-relaxed ${
          open ? '' : 'line-clamp-2'
        }`}
      >
        {story.summary}
      </p>

      {/* 照片：老人与家属都看得到；老人（viewer=elderly）可以删任意一张 */}
      <StoryPhotoStrip
        media={story.media || []}
        onDelete={viewer === 'elderly' ? onDeleteMedia : undefined}
      />

      {renderExtra?.(story)}

      <div className="mt-2 flex flex-wrap gap-2 text-sm text-gray-600">
        {story.place && <span>📍 {story.place}</span>}
        {story.people.map((p) => (
          <span key={p} className="bg-warm-light rounded-lg px-2 py-0.5">
            👤 {p}
          </span>
        ))}
        {story.emotion_tone && story.emotion_tone !== '平淡' && (
          <span className="text-gray-500">{story.emotion_tone}</span>
        )}
        {/* 多时代标签时，这里能看到卡片没丢掉的其它时代 */}
        {story.era_tags
          .filter((t) => t !== story.era)
          .map((t) => (
            <span key={t} className="text-gray-400 border border-gray-200 rounded px-1.5">
              {t}
            </span>
          ))}
      </div>

      {open && (
        <dl className="mt-3 border-t border-amber-100 pt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-base text-gray-600">
          {/* 契约5：原始记录与展示值并列摆出，原文只增不改，页面上没有纠正入口 */}
          <dt className="text-gray-400">老人原话里的时间</dt>
          <dd>{story.time_value || '（没提）'}</dd>
          <dt className="text-gray-400">记录下来的时间</dt>
          <dd>{story.display_time || '（没定）'}</dd>
          {story.people.length > 0 && (
            <>
              <dt className="text-gray-400">提到的人</dt>
              <dd>{story.people.join('、')}</dd>
            </>
          )}
          <dt className="text-gray-400">记下于</dt>
          <dd>{story.created_at ? story.created_at.slice(0, 10) : '—'}</dd>
        </dl>
      )}
    </li>
  );
}

/** 顶部时代带：按年代跨度给色块宽度，纯展示（色块不是唯一信息载体，旁边有文字）。 */
function EraBand({
  groups,
  span,
  onJump,
}: {
  groups: EraAxisGroup[];
  span: MemoirTimeline['axis_span'];
  onJump: (era: string) => void;
}) {
  const lo = span.min_year ?? 0;
  const hi = span.max_year ?? 0;
  const total = Math.max(1, hi - lo);

  return (
    <div className="bg-white rounded-2xl border border-amber-200 p-4 hc-invert">
      <div className="flex items-center justify-between text-sm text-gray-500 mb-2">
        <span>{lo} 年</span>
        <span>人生的几段日子</span>
        <span>{hi} 年</span>
      </div>
      <div className="flex items-stretch gap-1 h-14">
        {groups.map((g) => {
          const start = g.start_year ?? lo;
          const end = g.end_year ?? hi;
          // 最小宽度保证短时代（如三年困难时期）也点得到
          const width = Math.max(6, ((end - start) / total) * 100);
          return (
            <button
              key={g.era}
              onClick={() => onJump(g.era)}
              style={{ width: `${width}%`, backgroundColor: g.color || '#BA7517' }}
              className="rounded-lg flex flex-col items-center justify-center text-white text-sm font-bold px-1 overflow-hidden hover:opacity-90 transition-opacity"
              title={`${g.era}（${start}—${end}）${g.count} 段`}
            >
              <span className="truncate w-full text-center">{g.era}</span>
              <span className="text-xs opacity-90">{g.count} 段</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function StoryTimeline({
  timeline,
  viewer = 'elderly',
  onDeleteMedia,
  renderStoryExtra,
}: {
  timeline: MemoirTimeline;
  /** elderly = 老人端（可删照片）；family = 家属端（只读，另有 renderStoryExtra 补照片） */
  viewer?: 'elderly' | 'family';
  onDeleteMedia?: (m: StoryMediaItem) => void;
  /** 家属端用来在卡片里插「补一张照片」的入口 */
  renderStoryExtra?: (story: TimelineStory) => ReactNode;
}) {
  const [jumpTo, setJumpTo] = useState<string | null>(null);
  const { era_axis, absolute_axis, unlocated, stats, axis_span } = timeline;

  const empty = useMemo(
    () => stats.total === 0,
    [stats.total]
  );

  const blockProps = { viewer, onDeleteMedia, renderExtra: renderStoryExtra };

  if (empty) {
    return (
      <div className="bg-white rounded-2xl border border-amber-200 p-8 text-center hc-invert">
        <p className="text-xl text-gray-700">
          {viewer === 'family' ? '这里还空着。' : '这里还空着。'}
        </p>
        <p className="text-gray-500 mt-2">
          {viewer === 'family'
            ? '老人留档的回忆会慢慢攒到这里——只有老人愿意分享的那些。'
            : '您聊起从前的日子时，我记下来的事会慢慢攒到这里。'}
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <p className="text-gray-600">
        一共记下了 <strong className="text-warm-dark">{stats.total}</strong> 段回忆
        {stats.era_segments > 0 && <>，分在 {stats.era_segments} 个年代里</>}
        {stats.inferred > 0 && <>，其中 {stats.inferred} 段的时间是猜的（标了「时间存疑」）</>}。
      </p>

      {era_axis.length > 0 && (
        <>
          <EraBand groups={era_axis} span={axis_span} onJump={setJumpTo} />

          <section className="space-y-5">
            {era_axis.map((g) => (
              <div
                key={g.era}
                id={`era-${g.era}`}
                className={`rounded-2xl border-2 p-4 bg-warm-bg ${
                  jumpTo === g.era ? 'ring-4 ring-warm-primary' : ''
                }`}
                style={{ borderColor: g.color || '#BA7517' }}
              >
                <header className="flex items-baseline justify-between flex-wrap gap-2 mb-3">
                  <h3 className="text-xl font-bold text-gray-800">
                    <span
                      className="inline-block w-3 h-3 rounded-full mr-2"
                      style={{ backgroundColor: g.color || '#BA7517' }}
                      aria-hidden
                    />
                    {g.era}
                  </h3>
                  <span className="text-gray-500">
                    {g.start_year} — {g.end_year ?? '至今'} · {g.count} 段
                  </span>
                </header>
                <ul className="space-y-3">
                  {g.stories.map((s) => (
                    <StoryBlock key={`${g.era}-${s.id}`} story={s} {...blockProps} />
                  ))}
                </ul>
              </div>
            ))}
          </section>
        </>
      )}

      {absolute_axis.length > 0 && (
        <section>
          <h3 className="text-xl font-bold text-gray-800 mb-3">📅 按年排</h3>
          <ol className="border-l-4 border-warm-primary ml-2 space-y-3 pl-4">
            {absolute_axis.map((s) => (
              <li key={s.id} className="relative">
                <span
                  className="absolute -left-[26px] top-4 w-4 h-4 rounded-full bg-warm-primary border-4 border-warm-bg"
                  aria-hidden
                />
                <ul>
                  <StoryBlock story={s} {...blockProps} />
                </ul>
              </li>
            ))}
          </ol>
        </section>
      )}

      {unlocated.length > 0 && (
        <section>
          <h3 className="text-xl font-bold text-gray-800 mb-1">💭 还记得这些</h3>
          <p className="text-gray-500 mb-3">这些事老人没提是哪一年，就放在这儿。</p>
          <ul className="space-y-3">
            {unlocated.map((s) => (
              <StoryBlock key={s.id} story={s} {...blockProps} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  ApiError,
  CompilationItem,
  MemoirTimeline,
  StoryMediaItem,
  TimelineStory,
  familyApi,
} from '@/lib/api';
import { StoryTimeline } from '@/components/StoryTimeline';
import { StoryPhoto, StoryPhotoStrip, StoryPhotoUploader } from '@/components/StoryPhoto';
import {
  PromptCopyButton,
  StoryboardPlayer,
  StoryboardSceneList,
} from '@/components/StoryboardPlayer';

/**
 * 家属端「回忆录」面板。
 *
 * 设计取向：家属在这里**只能读，加两件事**——给看得见的往事补照片、撤回自己补的照片。
 * 确认留档、改可见性、排短片全部是老人专属（契约1）；创伤类 private 故事
 * 根本不会出现在这个面板里（服务端过滤，不是前端隐藏）。
 *
 * 所以这个组件里没有任何 `confirmStory` / `discardStory` / `createCompilation` 调用——
 * 那不是"忘了做"，是刻意不做。
 */
export function FamilyMemoirPanel({
  elderlyId,
  elderlyName,
  refreshKey = 0,
}: {
  elderlyId: string;
  elderlyName: string;
  /** 变化时重新拉取（老人新聊出一段回忆时的实时刷新，2026-10-15） */
  refreshKey?: number;
}) {
  const [timeline, setTimeline] = useState<MemoirTimeline | null>(null);
  const [compilations, setCompilations] = useState<CompilationItem[]>([]);
  const [activeComp, setActiveComp] = useState<number | null>(null);
  const [uploadFor, setUploadFor] = useState<number | null>(null);
  const [preview, setPreview] = useState<StoryMediaItem | null>(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError('');
    try {
      const tl = await familyApi.memoir(elderlyId);
      setTimeline(tl);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载回忆录失败');
      setTimeline(null);
    }
    try {
      const comps = await familyApi.memoirCompilations(elderlyId);
      setCompilations(comps || []);
    } catch {
      // 短片列表拿不到不影响时间轴，静默降级
      setCompilations([]);
    }
    setLoading(false);
  }, [elderlyId]);

  useEffect(() => {
    setActiveComp(null);
    setUploadFor(null);
    setPreview(null);
    setLoading(true);
    load();
  }, [load, refreshKey]);

  const flash = (text: string) => {
    setToast(text);
    setTimeout(() => setToast(''), 2500);
  };

  const handleUpload = async (storyId: number, file: File, caption: string) => {
    await familyApi.uploadStoryPhoto(elderlyId, storyId, file, caption);
    await load();
    flash('照片已经放到这段回忆旁边了，老人打开就能看到。');
  };

  const handleDelete = async (m: StoryMediaItem) => {
    try {
      await familyApi.deleteStoryMedia(elderlyId, m.id);
      await load();
      flash('照片已撤回。');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '撤回失败');
    }
  };

  // 所有照片摊平，供「家人补的照片」相册用
  const allStories: TimelineStory[] = timeline
    ? [
        ...timeline.era_axis.flatMap((g) => g.stories),
        ...timeline.absolute_axis,
        ...timeline.unlocated,
      ]
    : [];
  const familyPhotos = allStories
    .flatMap((s) => s.media || [])
    .filter((m) => m.uploaded_by_role === 'family');
  const active = compilations.find((c) => c.id === activeComp) || null;

  if (loading) {
    return <p className="text-muted text-lg">正在看看老人留下的回忆……</p>;
  }

  return (
    <section className="space-y-5">
      <div className="rounded-card bg-canvas border border-hairline p-4">
        <h2 className="text-xl font-bold text-ink">
          📖 {elderlyName} 的回忆录
        </h2>
        <p className="text-muted mt-1 leading-relaxed">
          这里只显示老人**愿意分享**的回忆。老人不想给别人看的，不会出现在这儿——
          也请您别催他多讲。
        </p>
      </div>

      {error && (
        <p className="rounded-btn bg-danger-soft border border-hairline text-danger p-4">{error}</p>
      )}
      {toast && (
        <p className="rounded-btn bg-success-soft border border-hairline text-success p-4">
          {toast}
        </p>
      )}

      {timeline && (
        <StoryTimeline
          timeline={timeline}
          viewer="family"
          renderStoryExtra={(story) => (
            <div className="mt-3">
              {uploadFor === story.id ? (
                <StoryPhotoUploader
                  storyTitle={story.title}
                  onCancel={() => setUploadFor(null)}
                  onUpload={(file, caption) => handleUpload(story.id, file, caption)}
                />
              ) : (
                <button
                  type="button"
                  onClick={() => setUploadFor(story.id)}
                  className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-ink hover:border-primary"
                >
                  📷 给这段补一张照片
                </button>
              )}
            </div>
          )}
        />
      )}

      {familyPhotos.length > 0 && (
        <section className="rounded-card border border-hairline bg-card p-5">
          <h3 className="text-lg font-bold text-ink">
            🖼️ 家人补的照片（{familyPhotos.length}）
          </h3>
          <p className="text-sm text-muted mt-1">
            这些是您和家人补上去的，老人打开回忆录就能看到。点右上角 × 可以撤回。
          </p>
          <StoryPhotoStrip media={familyPhotos} onDelete={handleDelete} onOpen={setPreview} />
        </section>
      )}

      {compilations.length > 0 && (
        <section className="rounded-card border border-hairline bg-card p-5 space-y-4">
          <div>
            <h3 className="text-lg font-bold text-ink">🎬 老人的短片故事板</h3>
            <p className="text-sm text-muted mt-1">
              老人把几段回忆排成了一条短片。这里给的是旁白和画面提示词，
              您可以复制到常用的视频工具里自己做成片子——本系统不替您生成画面。
            </p>
          </div>

          <div className="flex gap-2 flex-wrap">
            {compilations.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setActiveComp(activeComp === c.id ? null : c.id)}
                className={`min-h-[44px] px-4 rounded-btn border text-base ${
                  activeComp === c.id
                    ? 'bg-primary text-white border-primary'
                    : 'bg-card text-ink border-hairline'
                }`}
              >
                {c.title || '一段日子'} · {c.prompt_package?.scenes.length ?? 0} 段
              </button>
            ))}
          </div>

          {active && (
            <>
              <StoryboardPlayer compilation={active} />
              <div className="flex justify-end">
                <PromptCopyButton compilation={active} />
              </div>
              <hr className="border-hairline" />
              <StoryboardSceneList compilation={active} />
            </>
          )}
        </section>
      )}

      {preview && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setPreview(null)}
          role="dialog"
          aria-modal="true"
          aria-label="照片预览"
        >
          <div className="max-w-3xl w-full" onClick={(e) => e.stopPropagation()}>
            <StoryPhoto media={preview} className="w-full max-h-[75vh] object-contain bg-black/20" />
            <div className="flex items-center justify-between mt-3">
              <p className="text-white">{preview.caption || '回忆照片'}</p>
              <button
                type="button"
                onClick={() => setPreview(null)}
                className="min-h-[44px] px-4 rounded-btn bg-card text-ink"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

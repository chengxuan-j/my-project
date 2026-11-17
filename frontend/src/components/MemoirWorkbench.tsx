'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  ApiError,
  memoirApi,
  CompilationItem,
  MemoirStory,
  MemoirTimeline,
  StoryMediaItem,
} from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { StoryTimeline } from '@/components/StoryTimeline';
import { StoryPhotoUploader } from '@/components/StoryPhoto';
import { StoryComposer } from '@/components/StoryComposer';

/** 生成动画的最短展示时长：接口通常 2~4 秒就回来了，太快反而让人以为没做事。 */
const MIN_RENDER_MS = 3000;

export function MemoirWorkbench({ embedded = false }: { embedded?: boolean }) {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const [timeline, setTimeline] = useState<MemoirTimeline | null>(null);
  const [compilations, setCompilations] = useState<CompilationItem[]>([]);
  const [onlyArchived, setOnlyArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [progress, setProgress] = useState(0);
  const [uploadFor, setUploadFor] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.push('/login');
      return;
    }
    // 家属走 /family 家属端看板，这里只给老人自己看
    if (user?.role === 'family') {
      router.push('/family');
    }
  }, [hydrated, accessToken, user, router]);

  const load = useCallback(
    async (status: 'archived' | 'all') => {
      setError('');
      try {
        const [tl, comps] = await Promise.all([
          memoirApi.timeline(status),
          memoirApi.compilations().catch(() => [] as CompilationItem[]),
        ]);
        setTimeline(tl);
        setCompilations(comps);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : '回忆录加载失败');
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    if (!hydrated || !accessToken || user?.role === 'family') return;
    load(onlyArchived ? 'archived' : 'all');
  }, [hydrated, accessToken, user, onlyArchived, load]);

  const refresh = useCallback(
    () => load(onlyArchived ? 'archived' : 'all'),
    [load, onlyArchived]
  );

  const flash = (text: string) => {
    setNotice(text);
    setTimeout(() => setNotice(''), 2500);
  };

  const handleUploadPhoto = async (storyId: number, file: File, caption: string) => {
    await memoirApi.uploadStoryPhoto(storyId, file, caption);
    setUploadFor(null);
    await refresh();
    flash('照片加上了。');
  };

  const handleDeletePhoto = async (m: StoryMediaItem) => {
    try {
      await memoirApi.deleteMedia(m.id);
      await refresh();
      flash('照片删掉了。');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  useEffect(() => () => {
    if (progressTimer.current) clearInterval(progressTimer.current);
  }, []);

  const startProgress = () => {
    setProgress(0);
    progressTimer.current = setInterval(() => {
      // 爬升到 95% 停住，剩下 5% 等接口真的回来
      setProgress((p) => (p >= 95 ? 95 : p + Math.max(1, Math.round((95 - p) / 12))));
    }, 200);
  };

  const stopProgress = () => {
    if (progressTimer.current) clearInterval(progressTimer.current);
    progressTimer.current = null;
    setProgress(100);
  };

  /** 草稿箱里「用这段做短片」：只把这一段排成故事板，不掺别的回忆。 */
  const handleUseStoryForFilm = async (story: MemoirStory) => {
    const comp = await memoirApi.createCompilation({
      title: story.title || '我的一段回忆',
      story_ids: [story.id],
    });
    router.push(`/memoir/compilation/${comp.id}`);
  };

  const handleCreateCompilation = async () => {
    setError('');
    setRendering(true);
    startProgress();
    const startedAt = Date.now();
    try {
      const comp = await memoirApi.createCompilation({});
      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_RENDER_MS) {
        await new Promise((r) => setTimeout(r, MIN_RENDER_MS - elapsed));
      }
      stopProgress();
      router.push(`/memoir/compilation/${comp.id}`);
    } catch (err) {
      stopProgress();
      setError(err instanceof ApiError ? err.message : '整理失败，等会儿再试试');
    } finally {
      setRendering(false);
      setTimeout(() => setProgress(0), 600);
    }
  };

  if (!hydrated || !accessToken || user?.role === 'family') return null;

  const total = timeline?.stats.total ?? 0;

  return (
    <div className={embedded ? "" : "max-w-5xl mx-auto px-4 py-6"}>
      <div className="flex items-baseline justify-between flex-wrap gap-3 mb-4">
        <div>
          {!embedded && <h1 className="text-2xl font-bold text-ink">📖 我的回忆录</h1>}
          <p className="text-sm text-muted mt-1">
            这里是<strong>素材库</strong>：讲过的故事、照片和短片稿。
            确认留档后，故事才会进入《人生之书》。
          </p>
        </div>
        <label className="flex items-center gap-2 text-base text-ink min-h-[48px]">
          <input
            type="checkbox"
            checked={onlyArchived}
            onChange={(e) => setOnlyArchived(e.target.checked)}
            className="w-6 h-6 accent-amber-500"
          />
          只看已留档
        </label>
      </div>

      {error && (
        <p className="mb-4 rounded-btn bg-danger-soft border border-hairline text-danger p-4">
          {error}
        </p>
      )}
      {notice && (
        <p className="mb-4 rounded-btn bg-success-soft border border-hairline text-success p-4">
          {notice}
        </p>
      )}

      {/* 讲故事 → 存下来 → 再决定做不做短片 */}
      <StoryComposer onChanged={refresh} onUseForFilm={handleUseStoryForFilm} />

      {/* 做成短片：只在有已留档的故事时才亮 */}
      {!loading && (
        <section className="mb-6 rounded-card border border-hairline bg-card p-4 hc-invert">
          {rendering ? (
            <div>
              <p className="text-lg text-ink">正在把您讲的这些排成短片……</p>
              <div className="mt-3 h-4 rounded-full bg-primary-soft overflow-hidden">
                <div
                  className="h-full bg-primary transition-all duration-200"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <p className="mt-2 text-sm text-muted">差不多十几秒，您稍等。</p>
            </div>
          ) : (
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <p className="text-lg font-bold text-ink">把回忆做成一段短片</p>
                <p className="text-muted">
                  只出文字稿和画面提示词，不会生成视频。已留档 {total} 段。
                </p>
              </div>
              <button
                onClick={handleCreateCompilation}
                disabled={total === 0}
                className="min-h-[56px] px-6 rounded-btn bg-primary hover:bg-primary-strong text-white text-lg font-bold disabled:opacity-50 disabled:cursor-not-allowed"
              >
                🎬 做成短片
              </button>
            </div>
          )}
        </section>
      )}

      {compilations.length > 0 && (
        <section className="mb-6">
          <h2 className="text-lg font-bold text-ink mb-2">做过的短片稿</h2>
          <ul className="flex flex-wrap gap-2">
            {compilations.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/memoir/compilation/${c.id}`}
                  className="inline-flex items-center min-h-[48px] px-4 rounded-btn bg-primary-soft text-primary hover:bg-primary hover:text-white"
                >
                  {c.title || '未命名'} ·{' '}
                  {c.prompt_package?.total_seconds ?? 0} 秒
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {loading ? (
        <p className="text-muted text-lg">正在翻您的老照片……</p>
      ) : timeline ? (
        <StoryTimeline
          timeline={timeline}
          viewer="elderly"
          onDeleteMedia={handleDeletePhoto}
          renderStoryExtra={(story) =>
            uploadFor === story.id ? (
              <StoryPhotoUploader
                storyTitle={story.title}
                onCancel={() => setUploadFor(null)}
                onUpload={(file, caption) => handleUploadPhoto(story.id, file, caption)}
              />
            ) : (
              <button
                type="button"
                onClick={() => setUploadFor(story.id)}
                className="mt-3 min-h-[48px] px-4 rounded-btn bg-card border border-hairline text-ink hover:border-primary"
              >
                📷 加一张照片
              </button>
            )
          }
        />
      ) : null}
    </div>
  );
}

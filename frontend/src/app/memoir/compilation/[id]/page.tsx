'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Clapperboard, Trash2 } from 'lucide-react';
import { ApiError, CompilationItem, memoirApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { PageHeader } from '@/components/ui/PageHeader';
import {
  PromptCopyButton,
  StoryboardPlayer,
  StoryboardSceneList,
} from '@/components/StoryboardPlayer';

export default function CompilationPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const [comp, setComp] = useState<CompilationItem | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.push('/login');
      return;
    }
    if (user?.role === 'family') router.push('/family');
  }, [hydrated, accessToken, user, router]);

  useEffect(() => {
    if (!hydrated || !accessToken || user?.role === 'family') return;
    const id = Number(params?.id);
    if (!Number.isFinite(id)) {
      setError('这段短片不存在');
      setLoading(false);
      return;
    }
    memoirApi
      .compilation(id)
      .then(setComp)
      .catch((err) => setError(err instanceof ApiError ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [hydrated, accessToken, user, params]);

  const handleDelete = async () => {
    if (!comp) return;
    try {
      await memoirApi.deleteCompilation(comp.id);
      router.push('/book?tab=memoir');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  if (!hydrated || !accessToken || user?.role === 'family') return null;

  return (
    <main className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <Link href="/book?tab=memoir" className="text-primary min-h-[44px] flex items-center gap-1.5 text-sm font-medium">
          <ArrowLeft aria-hidden className="h-4 w-4" />
          回到素材库
        </Link>
        {comp && (
          <div className="flex items-center gap-2">
            <PromptCopyButton compilation={comp} />
            <button
              onClick={handleDelete}
              className="min-h-[44px] px-4 rounded-btn bg-card border border-hairline text-danger hover:bg-danger-soft flex items-center gap-1.5 text-sm font-medium"
            >
              <Trash2 aria-hidden className="h-4 w-4" />
              删掉这段
            </button>
          </div>
        )}
      </div>

      {comp && (
        <PageHeader
          eyebrow="回忆短片"
          title={comp.title || '一段回忆短片'}
          description="这里只有文字稿和画面提示词，本系统不替您生成画面。"
          icon={<Clapperboard aria-hidden className="h-7 w-7 text-primary" />}
        />
      )}

      {error && (
        <p className="rounded-btn bg-danger-soft text-danger p-4">{error}</p>
      )}
      {loading ? (
        <p className="text-muted text-lg">正在整理……</p>
      ) : comp ? (
        <>
          <StoryboardPlayer compilation={comp} />
          <hr className="border-hairline" />
          <StoryboardSceneList compilation={comp} />
          <p className="text-sm text-muted leading-relaxed">
            想变成真正的短片，可以把上面的提示词复制到您常用的视频工具里自己做。
          </p>
        </>
      ) : null}
    </main>
  );
}

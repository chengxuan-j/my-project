'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { ApiError, CompilationItem, memoirApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
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
      router.push('/memoir');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  if (!hydrated || !accessToken || user?.role === 'family') return null;

  return (
    <main className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <Link href="/memoir" className="text-warm-primary min-h-[48px] flex items-center">
          ← 回到回忆录
        </Link>
        {comp && (
          <div className="flex items-center gap-2">
            <PromptCopyButton compilation={comp} />
            <button
              onClick={handleDelete}
              className="min-h-[48px] px-4 rounded-xl bg-white border-2 border-red-300 text-red-600 hover:bg-red-50"
            >
              删掉这段
            </button>
          </div>
        )}
      </div>

      {error && (
        <p className="rounded-xl bg-red-50 border border-red-200 text-red-700 p-4">{error}</p>
      )}
      {loading ? (
        <p className="text-gray-500 text-lg">正在整理……</p>
      ) : comp ? (
        <>
          <StoryboardPlayer compilation={comp} />
          <hr className="border-amber-200" />
          <StoryboardSceneList compilation={comp} />
          <p className="text-sm text-gray-500 leading-relaxed">
            这里只有文字稿和画面提示词。想变成真正的短片，可以把上面的提示词复制到
            您常用的视频工具里自己做——本系统不替您生成画面。
          </p>
        </>
      ) : null}
    </main>
  );
}

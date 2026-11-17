'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { FileUp, Library, Search, Sparkles, Trash2 } from 'lucide-react';
import {
  ApiError,
  ElderlyItem,
  familyApi,
  KnowledgeDocument,
  KnowledgeHit,
  knowledgeApi,
} from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { PageHeader } from '@/components/ui/PageHeader';
import { SectionCard } from '@/components/ui/SectionCard';
import { StatCard } from '@/components/ui/StatCard';
import { Badge } from '@/components/ui/Badge';
import { EmptyState } from '@/components/ui/EmptyState';

export default function KnowledgePage() {
  const router = useRouter();
  const { user, accessToken } = useAuthStore();
  const [hydrated, setHydrated] = useState(false);
  const [authReady, setAuthReady] = useState(false);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [elderly, setElderly] = useState<ElderlyItem[]>([]);
  const [title, setTitle] = useState('');
  const [source, setSource] = useState('');
  const [content, setContent] = useState('');
  const [scope, setScope] = useState<'global' | 'elderly'>('global');
  const [elderlyId, setElderlyId] = useState('');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<KnowledgeHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const loadData = useCallback(async () => {
    try {
      const [docResp, elderlyResp] = await Promise.all([
        knowledgeApi.list(),
        familyApi.list(),
      ]);
      setDocuments(docResp.documents || []);
      const list = Array.isArray(elderlyResp) ? elderlyResp : elderlyResp.elderly || [];
      setElderly(list);
      if (list.length && !elderlyId) setElderlyId(list[0].elderly_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '知识库加载失败');
    }
  }, [elderlyId]);

  useEffect(() => setHydrated(true), []);
  useEffect(() => {
    // 等待 Zustand persist 完整恢复 user + token，避免首屏竞态把老人误判成未知角色。
    const persist = useAuthStore.persist;
    if (persist.hasHydrated()) {
      setAuthReady(true);
      return;
    }
    return persist.onFinishHydration(() => setAuthReady(true));
  }, []);
  useEffect(() => {
    if (!hydrated || !authReady) return;
    if (!accessToken) router.push('/login');
    else if (user?.role !== 'family') router.replace('/');
    else loadData();
  }, [hydrated, authReady, accessToken, user?.role, router, loadData]);

  const createDocument = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setMessage('');
    if (!title.trim() || !content.trim()) {
      setError('请填写标题和知识内容');
      return;
    }
    if (scope === 'elderly' && !elderlyId) {
      setError('请先绑定并选择一位老人');
      return;
    }
    setLoading(true);
    try {
      const doc = await knowledgeApi.create({
        title: title.trim(),
        source: source.trim(),
        content: content.trim(),
        scope,
        elderly_user_id: scope === 'elderly' ? elderlyId : undefined,
      });
      setMessage(`已完成 ${doc.chunk_count} 个知识分块`);
      setTitle('');
      setSource('');
      setContent('');
      await loadData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '导入失败');
    } finally {
      setLoading(false);
    }
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setError('');
    try {
      const result = await knowledgeApi.search(query.trim(), elderlyId || undefined);
      setHits(result.results || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '检索失败');
    } finally {
      setSearching(false);
    }
  };

  const remove = async (id: number) => {
    if (!window.confirm('确定删除这篇知识文档吗？')) return;
    try {
      await knowledgeApi.remove(id);
      setDocuments((items) => items.filter((item) => item.id !== id));
      setHits((items) => items.filter((item) => item.document_id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    }
  };

  if (!hydrated || !authReady) {
    return <div className="min-h-[50vh] flex items-center justify-center text-muted">正在打开知识库…</div>;
  }
  if (!accessToken || user?.role !== 'family') return null;

  const totalChunks = documents.reduce((sum, item) => sum + item.chunk_count, 0);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <PageHeader
        eyebrow="RAG Knowledge Center"
        title="陪伴知识库"
        description="把照护经验和家庭信息整理成 AI 可以检索的可靠资料。"
        icon={<Library aria-hidden className="h-7 w-7 text-primary" />}
      />

      <div className="grid grid-cols-2 gap-3 max-w-md">
        <StatCard label="文档" value={documents.length} unit="篇" icon={<Library aria-hidden className="h-4 w-4" />} />
        <StatCard label="知识分块" value={totalChunks} unit="块" tone="primary" icon={<Sparkles aria-hidden className="h-4 w-4" />} />
      </div>

      {(error || message) && (
        <div className={`rounded-btn px-4 py-3 ${error ? 'bg-danger-soft text-danger' : 'bg-success-soft text-success'}`}>
          {error || message}
        </div>
      )}

      <div className="grid lg:grid-cols-[1.05fr_0.95fr] gap-5 items-start">
        <SectionCard
          title="导入知识"
          icon={<FileUp aria-hidden className="h-5 w-5" />}
          meta="自动分块 + 向量化"
        >
          <form onSubmit={createDocument} className="space-y-4">
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="text-sm font-semibold text-ink">文档标题
                <input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-2 w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none font-normal bg-card" placeholder="例如：跌倒后的照护流程" />
              </label>
              <label className="text-sm font-semibold text-ink">来源
                <input value={source} onChange={(e) => setSource(e.target.value)} className="mt-2 w-full min-h-[48px] px-3 rounded-input border border-hairline focus:border-primary outline-none font-normal bg-card" placeholder="例如：家庭护理手册" />
              </label>
            </div>
            <div className="grid sm:grid-cols-2 gap-4">
              <label className="text-sm font-semibold text-ink">共享范围
                <select value={scope} onChange={(e) => setScope(e.target.value as 'global' | 'elderly')} className="mt-2 w-full min-h-[48px] px-3 rounded-input border border-hairline bg-card font-normal">
                  <option value="global">我的家庭共享</option><option value="elderly">指定老人专属</option>
                </select>
              </label>
              <label className="text-sm font-semibold text-ink">关联老人
                <select value={elderlyId} onChange={(e) => setElderlyId(e.target.value)} disabled={!elderly.length} className="mt-2 w-full min-h-[48px] px-3 rounded-input border border-hairline bg-card font-normal disabled:bg-card-soft">
                  {!elderly.length && <option value="">暂无绑定老人</option>}
                  {elderly.map((item) => <option key={item.elderly_id} value={item.elderly_id}>{item.name || item.username}</option>)}
                </select>
              </label>
            </div>
            <label className="block text-sm font-semibold text-ink">知识内容
              <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={9} className="mt-2 w-full p-4 rounded-card border border-hairline focus:border-primary outline-none resize-y font-normal leading-7 bg-card" placeholder="粘贴经过核实的知识内容……" />
            </label>
            <div className="flex items-center justify-between gap-3">
              <span className="text-xs text-faint">{content.length.toLocaleString()} / 200,000 字</span>
              <button disabled={loading} className="min-h-[48px] px-6 rounded-btn bg-primary hover:bg-primary-strong text-on-primary font-bold disabled:opacity-50">
                {loading ? '处理中…' : '导入并向量化'}
              </button>
            </div>
          </form>
        </SectionCard>

        <SectionCard
          title="检索实验台"
          icon={<Search aria-hidden className="h-5 w-5" />}
          meta="查看 RAG 召回了哪些资料"
        >
          <form onSubmit={search}>
            <div className="flex gap-2">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="min-w-0 flex-1 min-h-[48px] px-4 rounded-input bg-card-soft border border-hairline text-ink placeholder:text-faint outline-none focus:border-primary"
                placeholder="例如：跌倒后该怎么办？"
              />
              <button disabled={searching} className="px-5 min-h-[48px] rounded-btn bg-primary text-on-primary font-bold disabled:opacity-50">
                {searching ? '检索中' : '检索'}
              </button>
            </div>
            <div className="space-y-3 mt-4">
              {hits.length === 0 ? (
                <div className="rounded-btn border border-dashed border-hairline p-5 text-center text-sm text-faint">
                  检索结果会显示在这里
                </div>
              ) : (
                hits.map((hit) => (
                  <div key={hit.chunk_id} className="rounded-btn bg-card-soft border border-hairline p-4">
                    <div className="flex justify-between gap-3 items-start">
                      <strong className="text-ink">{hit.title}</strong>
                      <Badge tone="success">{Math.round(hit.score * 100)}% 匹配</Badge>
                    </div>
                    <p className="text-sm text-muted mt-2 leading-6 line-clamp-4">{hit.content}</p>
                    <p className="text-xs text-faint mt-2">{hit.source || '未填写来源'}</p>
                  </div>
                ))
              )}
            </div>
          </form>
        </SectionCard>
      </div>

      <SectionCard
        title="已导入文档"
        icon={<Library aria-hidden className="h-5 w-5" />}
        meta={documents.length > 0 ? `${documents.length} 篇` : undefined}
      >
        {documents.length === 0 ? (
          <EmptyState
            icon={<Library aria-hidden className="h-6 w-6" />}
            title="还没有知识文档"
            description="从上方导入第一篇吧，聊天时 AI 会自动检索这里的内容。"
          />
        ) : (
          <div className="grid md:grid-cols-2 gap-4">
            {documents.map((doc) => (
              <article key={doc.id} className="rounded-card border border-hairline p-5 hover:border-hairline-strong transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Badge tone={doc.scope === 'elderly' ? 'primary' : 'success'}>
                        {!doc.created_by ? '系统内置' : doc.scope === 'elderly' ? '老人专属' : '家庭共享'}
                      </Badge>
                      <span className="text-xs text-faint">{doc.chunk_count} 个分块</span>
                    </div>
                    <h3 className="font-bold text-ink mt-3 truncate">{doc.title}</h3>
                    <p className="text-sm text-muted mt-1 truncate">{doc.source || '未填写来源'}</p>
                  </div>
                  {doc.created_by ? (
                    <button
                      onClick={() => remove(doc.id)}
                      className="min-h-[40px] px-3 rounded-btn bg-danger-soft text-danger hover:bg-danger hover:text-on-primary text-sm font-semibold flex items-center gap-1"
                    >
                      <Trash2 aria-hidden className="h-3.5 w-3.5" />
                      删除
                    </button>
                  ) : (
                    <span className="text-xs text-faint pt-2">只读</span>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

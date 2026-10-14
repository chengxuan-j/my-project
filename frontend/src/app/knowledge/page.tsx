'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ApiError,
  ElderlyItem,
  familyApi,
  KnowledgeDocument,
  KnowledgeHit,
  knowledgeApi,
} from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

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
    return <div className="min-h-[50vh] flex items-center justify-center text-gray-500">正在打开知识库…</div>;
  }
  if (!accessToken || user?.role !== 'family') return null;

  const totalChunks = documents.reduce((sum, item) => sum + item.chunk_count, 0);

  return (
    <div className="max-w-6xl mx-auto px-4 py-6 space-y-6">
      <header className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-600">RAG Knowledge Center</p>
          <h1 className="text-3xl font-bold text-gray-900 mt-1">陪伴知识库</h1>
          <p className="text-gray-500 mt-1">把照护经验和家庭信息整理成 AI 可以检索的可靠资料。</p>
        </div>
        <div className="flex gap-3">
          <div className="bg-white border border-slate-200 rounded-2xl px-5 py-3 text-center shadow-sm">
            <p className="text-2xl font-bold text-gray-900">{documents.length}</p><p className="text-xs text-gray-500">文档</p>
          </div>
          <div className="bg-slate-900 rounded-2xl px-5 py-3 text-center shadow-sm">
            <p className="text-2xl font-bold text-amber-300">{totalChunks}</p><p className="text-xs text-slate-300">知识分块</p>
          </div>
        </div>
      </header>

      {(error || message) && (
        <div className={`rounded-xl border px-4 py-3 ${error ? 'bg-red-50 border-red-200 text-red-700' : 'bg-emerald-50 border-emerald-200 text-emerald-700'}`}>
          {error || message}
        </div>
      )}

      <div className="grid lg:grid-cols-[1.05fr_0.95fr] gap-6">
        <form onSubmit={createDocument} className="bg-white rounded-3xl border border-slate-200 p-6 shadow-sm space-y-4">
          <div><h2 className="text-xl font-bold text-gray-900">导入知识</h2><p className="text-sm text-gray-500 mt-1">第一版支持粘贴纯文本，系统会自动分块和向量化。</p></div>
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-gray-700">文档标题
              <input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-2 w-full min-h-[48px] px-3 rounded-xl border-2 border-slate-200 focus:border-amber-400 outline-none font-normal" placeholder="例如：跌倒后的照护流程" />
            </label>
            <label className="text-sm font-semibold text-gray-700">来源
              <input value={source} onChange={(e) => setSource(e.target.value)} className="mt-2 w-full min-h-[48px] px-3 rounded-xl border-2 border-slate-200 focus:border-amber-400 outline-none font-normal" placeholder="例如：家庭护理手册" />
            </label>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <label className="text-sm font-semibold text-gray-700">共享范围
              <select value={scope} onChange={(e) => setScope(e.target.value as 'global' | 'elderly')} className="mt-2 w-full min-h-[48px] px-3 rounded-xl border-2 border-slate-200 bg-white font-normal">
                <option value="global">我的家庭共享</option><option value="elderly">指定老人专属</option>
              </select>
            </label>
            <label className="text-sm font-semibold text-gray-700">关联老人
              <select value={elderlyId} onChange={(e) => setElderlyId(e.target.value)} disabled={!elderly.length} className="mt-2 w-full min-h-[48px] px-3 rounded-xl border-2 border-slate-200 bg-white font-normal disabled:bg-slate-100">
                {!elderly.length && <option value="">暂无绑定老人</option>}
                {elderly.map((item) => <option key={item.elderly_id} value={item.elderly_id}>{item.name || item.username}</option>)}
              </select>
            </label>
          </div>
          <label className="block text-sm font-semibold text-gray-700">知识内容
            <textarea value={content} onChange={(e) => setContent(e.target.value)} rows={10} className="mt-2 w-full p-4 rounded-2xl border-2 border-slate-200 focus:border-amber-400 outline-none resize-y font-normal leading-7" placeholder="粘贴经过核实的知识内容……" />
          </label>
          <div className="flex items-center justify-between gap-3"><span className="text-xs text-gray-400">{content.length.toLocaleString()} / 200,000 字</span><button disabled={loading} className="min-h-[48px] px-6 rounded-xl bg-amber-500 hover:bg-amber-600 text-white font-bold disabled:opacity-50">{loading ? '处理中…' : '导入并向量化'}</button></div>
        </form>

        <div className="space-y-6">
          <form onSubmit={search} className="rounded-3xl bg-slate-900 p-6 text-white shadow-lg">
            <h2 className="text-xl font-bold">检索实验台</h2><p className="text-sm text-slate-300 mt-1">输入老人可能提出的问题，查看 RAG 会召回哪些资料。</p>
            <div className="flex gap-2 mt-5"><input value={query} onChange={(e) => setQuery(e.target.value)} className="min-w-0 flex-1 min-h-[48px] px-4 rounded-xl bg-white/10 border border-white/20 text-white placeholder:text-slate-400 outline-none focus:border-amber-300" placeholder="例如：跌倒后该怎么办？" /><button disabled={searching} className="px-5 rounded-xl bg-amber-400 text-slate-900 font-bold disabled:opacity-50">{searching ? '检索中' : '检索'}</button></div>
            <div className="space-y-3 mt-5">
              {hits.length === 0 ? <div className="rounded-xl border border-dashed border-white/20 p-5 text-center text-sm text-slate-400">检索结果会显示在这里</div> : hits.map((hit) => (
                <div key={hit.chunk_id} className="rounded-xl bg-white/10 p-4"><div className="flex justify-between gap-3"><strong className="text-amber-200">{hit.title}</strong><span className="text-xs text-emerald-300">{Math.round(hit.score * 100)}% 匹配</span></div><p className="text-sm text-slate-200 mt-2 leading-6 line-clamp-4">{hit.content}</p><p className="text-xs text-slate-400 mt-2">{hit.source || '未填写来源'}</p></div>
              ))}
            </div>
          </form>
        </div>
      </div>

      <section className="bg-white rounded-3xl border border-slate-200 p-6 shadow-sm">
        <div className="flex items-center justify-between"><div><h2 className="text-xl font-bold text-gray-900">已导入文档</h2><p className="text-sm text-gray-500 mt-1">聊天时会自动检索，无需手动开启。</p></div></div>
        {documents.length === 0 ? <div className="mt-5 rounded-2xl bg-slate-50 p-8 text-center text-gray-500">还没有知识文档，从上方导入第一篇吧。</div> : <div className="grid md:grid-cols-2 gap-4 mt-5">{documents.map((doc) => (
          <article key={doc.id} className="rounded-2xl border border-slate-200 p-5 hover:border-amber-300 transition-colors"><div className="flex items-start justify-between gap-4"><div className="min-w-0"><div className="flex items-center gap-2"><span className={`text-xs font-bold rounded-full px-2 py-1 ${doc.scope === 'elderly' ? 'bg-violet-50 text-violet-700' : 'bg-cyan-50 text-cyan-700'}`}>{!doc.created_by ? '系统内置' : doc.scope === 'elderly' ? '老人专属' : '家庭共享'}</span><span className="text-xs text-gray-400">{doc.chunk_count} 个分块</span></div><h3 className="font-bold text-gray-900 mt-3 truncate">{doc.title}</h3><p className="text-sm text-gray-500 mt-1 truncate">{doc.source || '未填写来源'}</p></div>{doc.created_by ? <button onClick={() => remove(doc.id)} className="min-h-[40px] px-3 rounded-lg bg-red-50 text-red-600 hover:bg-red-100 text-sm font-semibold">删除</button> : <span className="text-xs text-gray-400 pt-2">只读</span>}</div></article>
        ))}</div>}
      </section>
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { bookApi, LifeBook } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { MemoirWorkbench } from '@/components/MemoirWorkbench';

const TONE_STAMP: Record<string, { ring: string; text: string; label: string }> = {
  amber: { ring: 'border-amber-400 text-amber-700', text: 'text-amber-800', label: '暖' },
  blue: { ring: 'border-sky-400 text-sky-700', text: 'text-sky-800', label: '涩' },
  gray: { ring: 'border-gray-300 text-gray-500', text: 'text-gray-700', label: '淡' },
};

/** 老人端「人生之书」：成书 + 素材库（原回忆录合并进来）。 */
export default function BookPage() {
  const { accessToken } = useAuthStore();
  const [book, setBook] = useState<LifeBook | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<'book' | 'memoir'>('book');

  // 旧地址 /memoir 会跳到 /book?tab=memoir
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get('tab') === 'memoir') {
      setTab('memoir');
    }
  }, []);

  useEffect(() => {
    if (!accessToken) return;
    bookApi
      .me()
      .then(setBook)
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
  }, [accessToken]);

  const tabs = (
    <div className="no-print flex items-center justify-between gap-3 flex-wrap">
      <div className="inline-flex rounded-full bg-warm-light p-1 gap-1">
        <button
          type="button"
          onClick={() => setTab('book')}
          className={`min-h-[44px] px-5 rounded-full font-bold ${
            tab === 'book' ? 'bg-white text-warm-dark shadow-sm' : 'text-gray-600'
          }`}
        >
          📗 成书
        </button>
        <button
          type="button"
          onClick={() => setTab('memoir')}
          className={`min-h-[44px] px-5 rounded-full font-bold ${
            tab === 'memoir' ? 'bg-white text-warm-dark shadow-sm' : 'text-gray-600'
          }`}
        >
          📖 素材库
        </button>
      </div>
      <p className="text-xs text-gray-500">素材库里确认留档的故事，才会装订进书里</p>
    </div>
  );

  if (tab === 'memoir') {
    return (
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
        {tabs}
        <MemoirWorkbench embedded />
      </div>
    );
  }

  if (loading) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {tabs}
        <p className="py-10 text-center text-gray-500 text-lg">正在装订你的人生之书…</p>
      </div>
    );
  }

  if (error || !book) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
        {tabs}
        <div className="py-10 text-center text-gray-500">
          <p className="text-lg">这本书还没装订好</p>
          <p className="text-sm mt-2">{error || '稍后再试试'}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
      {tabs}
      <style>{`
        @media print {
          header { display: none !important; }
          .no-print { display: none !important; }
          .book-page { box-shadow: none !important; border: none !important; }
          body { background: #fff; }
        }
      `}</style>

      {/* 封面 */}
      <section className="book-page bg-[#FDF8EF] border-2 border-amber-200 rounded-3xl px-6 py-14 text-center shadow-sm">
        <p className="text-sm tracking-[0.3em] text-amber-600">一 生 一 书</p>
        <h1 className="font-serif text-4xl font-bold text-gray-900 mt-6 leading-relaxed">
          {book.title}
        </h1>
        <div className="flex items-center justify-center gap-3 mt-6 text-gray-400">
          <span className="h-px w-12 bg-amber-300" />
          <span className="text-2xl">❦</span>
          <span className="h-px w-12 bg-amber-300" />
        </div>
        <p className="text-lg text-gray-700 mt-6">
          {book.author_name}
          {book.age ? ` · ${book.age} 岁` : ''} 著
        </p>
        <p className="text-sm text-gray-500 mt-2">
          全书 {book.chapter_count} 章 · 收录 {book.story_count} 段人生回忆
        </p>
        <p className="no-print text-xs text-amber-700/70 mt-3">
          只收录在「回忆录」里确认留档的故事；还没确认的素材不会进书。
        </p>
        <div className="no-print mt-8 flex justify-center gap-3 flex-wrap">
          <button
            type="button"
            onClick={() => window.print()}
            className="min-h-[48px] px-5 rounded-xl bg-warm-primary text-white font-bold hover:bg-warm-dark"
          >
            🖨 打印 / 保存为 PDF
          </button>
          <Link
            href="/journey"
            className="min-h-[48px] px-5 rounded-xl bg-white border-2 border-warm-light text-gray-700 font-bold flex items-center hover:border-warm-primary"
          >
            ← 回人生河
          </Link>
        </div>
      </section>

      {/* 章节 */}
      {book.chapters.length === 0 ? (
        <section className="bg-white rounded-2xl border-2 border-warm-light p-10 text-center">
          <p className="text-lg text-gray-600">这本书还是空白的。</p>
          <p className="text-gray-500 mt-2">
            书只收录你<strong>确认留档</strong>的故事。去「回忆录」把讲过的往事留下来，
            这里就会一章一章长出来。
          </p>
          <div className="no-print mt-4 flex justify-center gap-3 flex-wrap">
            <Link
              href="/book?tab=memoir"
              className="inline-flex items-center min-h-[48px] px-5 rounded-xl bg-warm-primary text-white font-bold"
            >
              📖 去素材库看看
            </Link>
            <Link
              href="/"
              className="inline-flex items-center min-h-[48px] px-5 rounded-xl bg-white border-2 border-warm-light text-gray-700 font-bold"
            >
              💬 去聊会儿天
            </Link>
          </div>
        </section>
      ) : (
        book.chapters.map((chapter, ci) => (
          <section key={chapter.stage} className="space-y-4">
            {/* 章节扉页 */}
            <div className="book-page bg-[#FDF8EF] border border-amber-200 rounded-2xl px-6 py-8 text-center">
              <p className="text-sm text-amber-600 tracking-widest">第 {ci + 1} 章</p>
              <h2 className="font-serif text-3xl font-bold text-gray-900 mt-2">{chapter.stage}</h2>
              <p className="font-serif text-gray-600 mt-4 leading-loose">{chapter.intro}</p>
            </div>
            {/* 正文 */}
            {chapter.stories.map((story) => {
              const stamp = TONE_STAMP[story.tone_color] || TONE_STAMP.gray;
              return (
                <article
                  key={story.id}
                  className={`book-page bg-white rounded-2xl border-l-4 ${stamp.ring.split(' ')[0]} shadow-sm px-6 py-5`}
                >
                  <div className="flex items-baseline justify-between gap-3 flex-wrap">
                    <h3 className="font-serif text-xl font-bold text-gray-900">{story.title}</h3>
                    <span className={`text-xs border rounded-full px-2 py-0.5 ${stamp.ring}`}>
                      {story.emotion_tone}
                    </span>
                  </div>
                  {story.time_value && (
                    <p className="text-xs text-gray-400 mt-1">—— {story.time_value}</p>
                  )}
                  <p className="font-serif text-gray-800 mt-3 leading-loose text-[17px]">
                    {story.summary || '（这段回忆还没写下正文）'}
                  </p>
                </article>
              );
            })}
          </section>
        ))
      )}

      {/* 封底 */}
      {book.chapters.length > 0 && (
        <section className="book-page bg-[#FDF8EF] border-2 border-amber-200 rounded-3xl px-6 py-10 text-center">
          <p className="font-serif text-gray-600 leading-loose">
            这本书由陪伴 AI 根据日常聊天整理而成，
            <br />
            每一段都是{book.author_name}亲口讲过的往事。
          </p>
          <p className="text-sm text-gray-400 mt-4">—— 完 ——</p>
        </section>
      )}
    </div>
  );
}

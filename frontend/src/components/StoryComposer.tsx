'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { ApiError, memoirApi, MemoirStory, speechApi } from '@/lib/api';
import { DEMO_SCRIPTS, matchScriptReply } from '@/data/demo-stories';

interface Props {
  /** 保存/删除成功后通知外层刷新（素材库时间轴、短片稿数量） */
  onChanged?: () => void;
  /** 「用这段做短片」：外层负责创建短片稿并跳转 */
  onUseForFilm?: (story: MemoirStory) => void | Promise<void>;
}

type Turn = { role: 'user' | 'assistant'; content: string; scene?: string };

/** 开场白不算追问，只是让老人知道可以随便开口。 */
const GREETING = '您想说说哪段往事？随便开个头，我接着问。';

/** 单段录音上限：两分钟足够讲清一件事，也避免误触后一直录下去。 */
const MAX_RECORD_SECONDS = 120;

function formatDate(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`;
}

/**
 * 短片故事草稿箱（对话版）：像聊天一样把一段往事讲完整。
 *
 * 老人说一句 → 小忆顺着这句话追问下一句 → 老人接着答，直到讲清楚 → 一键存下来。
 * 追问只是"问什么"，不改写老人的话；存的时候原话原样入库，追问也一并留底。
 *
 * 语音只用一次性转写接口，**不触发**聊天的「边说边算」预生成——
 * 这里老人是在讲素材，不是在等陪聊回复，触发预生成既费额度又会串话。
 */
export function StoryComposer({ onChanged, onUseForFilm }: Props) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [thinking, setThinking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [drafts, setDrafts] = useState<MemoirStory[]>([]);
  const [loading, setLoading] = useState(true);
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [filmId, setFilmId] = useState<number | null>(null);
  // 演示脚本：固定剧本、固定回答，现场不依赖模型
  const [showScripts, setShowScripts] = useState(false);
  const [demo, setDemo] = useState<{ scriptId: string; index: number; playing: boolean } | null>(
    null
  );

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // 这一轮是否用过语音（保存时只做来源记录，不影响内容）
  const usedVoiceRef = useRef(false);

  const userTurns = turns.filter((t) => t.role === 'user');
  const userCount = userTurns.length;
  const demoScript = demo ? DEMO_SCRIPTS.find((s) => s.id === demo.scriptId) : undefined;

  const flash = (text: string) => {
    setNotice(text);
    setTimeout(() => setNotice(''), 3000);
  };

  const loadDrafts = useCallback(async () => {
    try {
      setDrafts(await memoirApi.manualStories());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '故事列表没读出来');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDrafts();
  }, [loadDrafts]);

  // 新消息进来后滚到底：老人不会自己去拖滚动条
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, thinking]);

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    mediaRecorderRef.current?.stream.getTracks().forEach((t) => t.stop());
  }, []);

  // 录满上限自动收：老人很可能说完就忘了点按钮
  useEffect(() => {
    if (!recording || seconds < MAX_RECORD_SECONDS) return;
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setRecording(false);
    mediaRecorderRef.current?.stop();
  }, [recording, seconds]);

  // 演示脚本自动播放：一句一句往外铺，演讲的人可以随时暂停
  useEffect(() => {
    if (!demo || !demo.playing || !demoScript) return;
    if (demo.index >= demoScript.turns.length) return;
    // 按句子长短决定停顿：短句快、长句慢，听着像真的在说
    const current = demoScript.turns[demo.index];
    const delay =
      demo.index === 0 ? 400 : 600 + Math.min(1500, (current?.content.length || 10) * 70);
    const timer = setTimeout(() => {
      const nextTurn = demoScript.turns[demo.index];
      setTurns((prev) => [...prev, nextTurn]);
      setDemo((d) => {
        if (!d) return d;
        const nextIndex = d.index + 1;
        return { ...d, index: nextIndex, playing: nextIndex < demoScript.turns.length };
      });
      if (demo.index + 1 >= demoScript.turns.length) {
        flash('演示结束，可以点「存到我的故事」。');
      }
    }, delay);
    return () => clearTimeout(timer);
  }, [demo, demoScript]);

  const startDemo = (scriptId: string) => {
    setTurns([]);
    setDraft('');
    setError('');
    setShowScripts(false);
    setDemo({ scriptId, index: 0, playing: true });
  };

  const exitDemo = () => {
    setDemo(null);
    setTurns([]);
    setDraft('');
  };

  const sendText = async () => {
    const text = draft.trim();
    if (!text || thinking || saving) return;
    const nextTurns: Turn[] = [...turns, { role: 'user', content: text }];
    setTurns(nextTurns);
    setDraft('');
    setError('');

    // 演示台词：命中脚本就照脚本回答，不调模型（现场最怕的就是这一下卡住）
    const scripted = matchScriptReply(text);
    if (scripted) {
      setThinking(true);
      setTimeout(() => {
        setTurns([...nextTurns, { role: 'assistant', content: scripted }]);
        setThinking(false);
      }, 450);
      return;
    }

    setThinking(true);
    try {
      const r = await memoirApi.storyDraftNext(nextTurns);
      setTurns([...nextTurns, { role: 'assistant', content: r.question }]);
    } catch (err) {
      // 追问失败不挡路：老人还能接着说，也能直接把这段存下来
      setTurns([
        ...nextTurns,
        { role: 'assistant', content: '我这会儿没太听清，您接着说，说完了直接点下面保存也行。' },
      ]);
      setError(err instanceof ApiError ? err.message : '追问暂时没接上，不影响保存。');
    } finally {
      setThinking(false);
    }
  };

  const handleSave = async () => {
    const content = userTurns.map((t) => t.content.trim()).filter(Boolean).join('\n');
    if (content.length < 2) {
      setError('再多说一句吧，我还没听明白这段事。');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const story = await memoirApi.createManualStory({
        content,
        input_type: usedVoiceRef.current ? 'voice' : 'text',
        turns,
      });
      setDrafts((prev) => [story, ...prev]);
      setTurns([]);
      setDemo(null);
      usedVoiceRef.current = false;
      flash('这段存好了，可以做成短片。');
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '没存上，等会儿再试试。');
    } finally {
      setSaving(false);
    }
  };

  const startRecording = async () => {
    setError('');
    // 手机用局域网 IP 打开时不是安全上下文，浏览器直接禁掉麦克风。
    if (
      typeof window !== 'undefined' &&
      (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
    ) {
      setError('当前地址下浏览器不给用麦克风：可以先用文字写，或者在电脑上用 localhost 打开再录音。');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        if (blob.size === 0) {
          setError('这次没录到声音，再试一次吧。');
          return;
        }
        setTranscribing(true);
        try {
          const res = await speechApi.transcribe(blob, undefined, 'story.webm');
          const text = (res.text || '').trim();
          if (!text) {
            setError('没听清，您用文字补一句也行。');
            return;
          }
          usedVoiceRef.current = true;
          // 先放进输入框让老人看一眼，确认没认错字再发送
          setDraft((prev) => (prev.trim() ? `${prev.trim()} ${text}` : text));
          flash('听好了，没错就点「发送」。');
        } catch (err) {
          setError(err instanceof ApiError ? err.message : '语音没转成文字，您先用文字说一句。');
        } finally {
          setTranscribing(false);
        }
      };
      mediaRecorderRef.current = mr;
      mr.start(1000);
      setSeconds(0);
      setRecording(true);
      timerRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    } catch {
      setError('没能打开麦克风，您可以先用文字说。');
    }
  };

  const stopRecording = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setRecording(false);
    mediaRecorderRef.current?.stop();
  };

  const handleDelete = async (story: MemoirStory) => {
    setDeletingId(story.id);
    setError('');
    try {
      await memoirApi.deleteStory(story.id);
      setDrafts((prev) => prev.filter((s) => s.id !== story.id));
      setConfirmId(null);
      flash('这段故事和它的短片稿一起删掉了。');
      onChanged?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '没删掉，等会儿再试试。');
    } finally {
      setDeletingId(null);
    }
  };

  const handleUseForFilm = async (story: MemoirStory) => {
    if (!onUseForFilm) return;
    setFilmId(story.id);
    setError('');
    try {
      await onUseForFilm(story);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '短片稿没排出来，等会儿再试试。');
    } finally {
      setFilmId(null);
    }
  };

  return (
    <section className="mb-6 rounded-2xl border-2 border-warm-light bg-warm-bg p-4 hc-invert">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold text-gray-900">🎤 聊聊想做成短片的故事</h2>
        <div className="flex items-center gap-2">
          <span className="text-sm text-gray-500">您说一句，小忆接一句</span>
          {!demo && userCount === 0 && (
            <button
              type="button"
              onClick={() => setShowScripts((v) => !v)}
              className="min-h-[40px] px-3 rounded-lg bg-white border border-warm-light text-sm text-gray-600 hover:border-warm-primary"
            >
              {showScripts ? '收起脚本' : '🎬 演示脚本'}
            </button>
          )}
        </div>
      </div>

      {/* 演示脚本选择：固定台词 + 固定回答，不走模型 */}
      {showScripts && !demo && (
        <div className="mt-3 rounded-xl border border-warm-light bg-white p-3">
          <p className="text-sm text-gray-600">
            选一段，自动一句句铺开；也可以照着台词念，小忆会按脚本回答。
          </p>
          <div className="mt-2 flex flex-wrap gap-3">
            {DEMO_SCRIPTS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => startDemo(s.id)}
                className="min-h-[56px] flex-1 min-w-[240px] text-left rounded-xl border-2 border-warm-light bg-warm-bg px-4 py-3 hover:border-warm-primary"
              >
                <span className="block text-lg font-bold text-gray-900">
                  {s.title}
                  {s.id === 'night-road' && (
                    <span className="ml-2 rounded-full bg-warm-primary px-2 py-0.5 text-xs text-white align-middle">
                      推荐
                    </span>
                  )}
                </span>
                <span className="block text-sm text-gray-600">{s.subtitle}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 演示进行中的控制条 */}
      {demo && demoScript && (
        <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3 flex flex-wrap items-center gap-3">
          <span className="text-sm text-amber-800 font-bold">
            演示中：{demoScript.title}（{Math.min(demo.index, demoScript.turns.length)}/
            {demoScript.turns.length}）
          </span>
          <button
            type="button"
            onClick={() => setDemo((d) => (d ? { ...d, playing: !d.playing } : d))}
            className="min-h-[44px] px-4 rounded-lg bg-white border border-amber-300 text-amber-800 font-bold"
          >
            {demo.playing ? '⏸ 暂停' : '▶ 继续'}
          </button>
          <button
            type="button"
            onClick={() => {
              if (!demo) return;
              setTurns([]);
              setDemo({ scriptId: demo.scriptId, index: 0, playing: true });
            }}
            className="min-h-[44px] px-4 rounded-lg bg-white border border-amber-300 text-amber-800 font-bold"
          >
            ↺ 重来
          </button>
          <button
            type="button"
            onClick={exitDemo}
            className="min-h-[44px] px-4 rounded-lg bg-white border border-gray-300 text-gray-600 font-bold"
          >
            退出演示
          </button>
        </div>
      )}

      {/* 对话区 */}
      <div
        ref={scrollRef}
        className="mt-3 max-h-[420px] overflow-y-auto rounded-xl bg-white/60 p-3 space-y-3"
      >
        <Bubble role="assistant">{GREETING}</Bubble>
        {turns.map((t, i) => (
          <div key={i}>
            {t.scene && (
              <div className="my-3 flex items-center gap-2 text-sm text-gray-500">
                <span className="h-px flex-1 bg-warm-light" />
                <span className="shrink-0 rounded-full bg-warm-light px-3 py-1 text-warm-dark font-bold">
                  {t.scene}
                </span>
                <span className="h-px flex-1 bg-warm-light" />
              </div>
            )}
            <Bubble role={t.role}>{t.content}</Bubble>
          </div>
        ))}
        {thinking && (
          <Bubble role="assistant">
            <span className="text-gray-500">小忆在想…</span>
          </Bubble>
        )}
      </div>

      {/* 输入区：演示时收起，避免误触打断脚本 */}
      {!demo && (
        <div className="mt-3">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // 中文输入法组字时按回车是在选字，不能当发送
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void sendText();
              }
            }}
            rows={2}
            placeholder="想到哪儿说到哪儿，比如：我十七岁那年去修水库……"
            className="w-full rounded-xl border-2 border-warm-light bg-white p-3 text-lg leading-relaxed text-gray-900 placeholder:text-gray-400 focus:border-warm-primary focus:outline-none"
          />

          <div className="mt-2 flex flex-wrap items-center gap-3">
            {recording ? (
              <button
                type="button"
                onClick={stopRecording}
                className="min-h-[56px] px-6 rounded-xl bg-red-600 hover:bg-red-700 text-white text-lg font-bold"
              >
                ⏹ 说完了（{seconds} 秒）
              </button>
            ) : (
              <button
                type="button"
                onClick={startRecording}
                disabled={transcribing || thinking || saving}
                className="min-h-[56px] px-6 rounded-xl bg-white border-2 border-warm-primary text-warm-dark text-lg font-bold disabled:opacity-50"
              >
                🎙 用嘴说
              </button>
            )}

            <button
              type="button"
              onClick={() => void sendText()}
              disabled={!draft.trim() || thinking || recording || transcribing}
              className="min-h-[56px] px-6 rounded-xl bg-warm-primary hover:bg-warm-dark text-white text-lg font-bold disabled:opacity-50 disabled:cursor-not-allowed"
            >
              发送
            </button>

            {transcribing && <span className="text-gray-600 text-lg">正在听您说……</span>}

            {userCount > 0 && (
              <button
                type="button"
                onClick={() => {
                  setTurns([]);
                  setDraft('');
                  usedVoiceRef.current = false;
                }}
                className="ml-auto min-h-[48px] px-4 rounded-xl bg-white border border-gray-300 text-gray-600"
              >
                重新说一段
              </button>
            )}
          </div>
        </div>
      )}

      {demo && (
        <p className="mt-3 text-sm text-amber-800">
          演示模式：台词按脚本自动往下走，铺完或点「暂停」后可以直接保存。
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-gray-600">
          {userCount === 0
            ? '说一句就能开始，小忆会顺着您的话往下问。'
            : `已经说了 ${userCount} 句，可以接着说，也可以随时全部存下来。`}
        </p>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving || userCount === 0}
          className="min-h-[56px] px-6 rounded-xl bg-warm-primary hover:bg-warm-dark text-white text-lg font-bold disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saving ? '正在存……' : '💾 存到我的故事'}
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-xl bg-red-50 border border-red-200 text-red-700 p-3">{error}</p>
      )}
      {notice && (
        <p className="mt-3 rounded-xl bg-green-50 border border-green-200 text-green-700 p-3">{notice}</p>
      )}

      <div className="mt-5">
        <div className="flex items-baseline justify-between">
          <h3 className="text-lg font-bold text-gray-800">我存的故事</h3>
          <span className="text-sm text-gray-500">
            {loading ? '正在读……' : `共 ${drafts.length} 段`}
          </span>
        </div>

        {!loading && drafts.length === 0 && (
          <p className="mt-2 text-gray-500">还没有存过。聊完一段，点「存到我的故事」就出现在这里。</p>
        )}

        <ul className="mt-2 space-y-3">
          {drafts.map((story) => (
            <li key={story.id} className="rounded-xl border border-warm-light bg-white p-4">
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <p className="text-lg font-bold text-gray-900">{story.title || '一段回忆'}</p>
                <span className="text-sm text-gray-500">{formatDate(story.created_at)}</span>
              </div>
              <p className="mt-1 text-gray-700 leading-relaxed whitespace-pre-wrap max-h-40 overflow-y-auto">
                {story.summary}
              </p>

              {confirmId === story.id ? (
                <div className="mt-3 flex flex-wrap items-center gap-3 rounded-xl bg-red-50 border border-red-200 p-3">
                  <p className="text-red-700">删掉就找不回来了，确定吗？</p>
                  <button
                    type="button"
                    onClick={() => handleDelete(story)}
                    disabled={deletingId === story.id}
                    className="min-h-[48px] px-5 rounded-xl bg-red-600 text-white font-bold disabled:opacity-50"
                  >
                    {deletingId === story.id ? '正在删……' : '确定删除'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmId(null)}
                    className="min-h-[48px] px-5 rounded-xl bg-white border border-gray-300 text-gray-700 font-bold"
                  >
                    先不删
                  </button>
                </div>
              ) : (
                <div className="mt-3 flex flex-wrap gap-3">
                  {onUseForFilm && (
                    <button
                      type="button"
                      onClick={() => handleUseForFilm(story)}
                      disabled={filmId === story.id}
                      className="min-h-[48px] px-5 rounded-xl bg-warm-primary text-white font-bold disabled:opacity-50"
                    >
                      {filmId === story.id ? '正在排……' : '🎬 用这段做短片'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setConfirmId(story.id)}
                    className="min-h-[48px] px-5 rounded-xl bg-white border border-gray-300 text-gray-700 font-bold hover:border-red-400 hover:text-red-600"
                  >
                    🗑 删除
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: ReactNode }) {
  const isUser = role === 'user';
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <span className="mr-2 mt-1 shrink-0 w-9 h-9 rounded-full bg-warm-light text-warm-dark flex items-center justify-center text-sm font-bold">
          小忆
        </span>
      )}
      <p
        className={`max-w-[82%] rounded-2xl px-4 py-3 text-lg leading-relaxed whitespace-pre-wrap ${
          isUser
            ? 'bg-warm-primary text-white rounded-br-md'
            : 'bg-white border border-warm-light text-gray-900 rounded-bl-md'
        }`}
      >
        {children}
      </p>
    </div>
  );
}

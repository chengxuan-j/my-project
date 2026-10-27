'use client';

import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { chatApi, dogApi, ApiError, recommendApi, familyMessageApi, FamilyMessageItem, FamilyPerson, memoirApi, MemoirStory, speechApi } from '@/lib/api';
import { useServerEvents } from '@/lib/events';
import { useAuthStore } from '@/stores/auth';
import { useSettingsStore } from '@/stores/settings';
import { ChatMessage, Message } from '@/components/ChatMessage';
import { VoiceRecorder } from '@/components/VoiceRecorder';
import { TTSPlayer } from '@/components/TTSPlayer';
import { LargeButton } from '@/components/LargeButton';
import { SpeakButton } from '@/components/SpeakButton';
import { CameraPanel } from '@/components/CameraPanel';
import { StoryConfirmCard } from '@/components/StoryConfirmCard';

interface RecommendItem {
  title: string;
  subtitle?: string;
  detail?: string;
  searchUrl?: string;
  speakText?: string;
}

interface Recommendation {
  // 快捷推荐（听首歌 / 听故事）
  kind?: 'music' | 'story';
  items?: RecommendItem[];
  // 聊天回复中返回的推荐
  type?: string;
  title?: string;
  content?: string;
  url?: string;
}

const QUICK_PHRASES = [
  '我今天有点闷',
  '我睡不着',
  '我想孩子了',
  '今天天气不错',
  '陪我聊聊天吧',
];

const MSG_CATEGORIES = [
  { value: 'greeting', label: '问候', emoji: '👋' },
  { value: 'care', label: '关心', emoji: '🤗' },
  { value: 'remind', label: '叮嘱', emoji: '📌' },
  { value: 'miss', label: '想念', emoji: '💝' },
];

export default function ChatPage() {
  const router = useRouter();
  const { user, accessToken } = useAuthStore();
  const autoTTS = useSettingsStore((s) => s.autoTTS);
  const toggleAutoTTS = useSettingsStore((s) => s.toggleAutoTTS);

  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'assistant',
      content: '您好呀！我是您的贴心陪伴 🌻，可以陪我聊聊天吗？',
      timestamp: Date.now(),
    },
  ]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [lastReply, setLastReply] = useState<string | null>(null);
  // 流式路径已经逐句播过音，此时 TTSPlayer 只留"重播"按钮、不再自动播放
  const [autoSpoken, setAutoSpoken] = useState(false);

  // 共享播放队列：正式回复的逐句音频排队播出，避免两句叠在一起。
  // （2026-10-20 移除"接话短句"——AI 回答前那句预合成的"嗯，我在呢"
  //   听感生硬，用户要求去掉。队列本身保留，按句 TTS 仍在用。）
  const audioQueueRef = useRef<string[]>([]);
  const audioPlayingRef = useRef(false);
  const drainAudioQueue = useCallback(() => {
    const url = audioQueueRef.current.shift();
    if (!url) {
      audioPlayingRef.current = false;
      return;
    }
    audioPlayingRef.current = true;
    const audio = new Audio(url);
    audio.onended = drainAudioQueue;
    audio.onerror = drainAudioQueue;
    audio.play().catch(() => {
      audioPlayingRef.current = false;
    });
  }, []);
  const enqueueAudio = useCallback((url: string) => {
    audioQueueRef.current.push(url);
    if (!audioPlayingRef.current) drainAudioQueue();
  }, [drainAudioQueue]);

  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [recPool, setRecPool] = useState<RecommendItem[]>([]);
  const [recOffset, setRecOffset] = useState(0);
  const [famInbox, setFamInbox] = useState<FamilyMessageItem[]>([]);
  const [famSent, setFamSent] = useState<FamilyMessageItem[]>([]);
  const [famFamilies, setFamFamilies] = useState<FamilyPerson[]>([]);
  const [famUnread, setFamUnread] = useState(0);
  const [famOpen, setFamOpen] = useState(false);
  const [famComposeOpen, setFamComposeOpen] = useState(false);
  const [famTarget, setFamTarget] = useState('');
  const [famCategory, setFamCategory] = useState('greeting');
  const [famContent, setFamContent] = useState('');
  const [sendingFam, setSendingFam] = useState(false);
  const [cameraOpen, setCameraOpen] = useState(false);
  const [dogRelay, setDogRelay] = useState<{ text: string; relation?: string; content?: string; dogSpoke?: boolean } | null>(null);
  // 回忆录：待老人确认的往事条目（一次只展示一条）
  const [pendingStories, setPendingStories] = useState<MemoirStory[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !accessToken) {
      router.push('/login');
      return;
    }
    // 家属不能进聊天页，重定向到家属看板
    if (hydrated && accessToken && user?.role === 'family') {
      router.push('/family');
    }
  }, [hydrated, accessToken, user, router]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  // 家人的牵挂：进页面拉取一次（收件箱 + 我发出的 + 家属列表）
  useEffect(() => {
    if (!hydrated || !accessToken || user?.role !== 'elderly') return;
    familyMessageApi
      .received()
      .then((res) => {
        setFamInbox(res.inbox || []);
        setFamSent(res.sent || []);
        setFamUnread(res.unread || 0);
        if ((res.unread || 0) > 0) setFamOpen(true);
      })
      .catch(() => {});
    // 上线补播：发作时不在线的「小狗传话」，登录后由小狗补念一次
    dogApi
      .pendingRelays()
      .then((res) => {
        const list = res.relays || [];
        if (list.length > 0) {
          const last = list[list.length - 1];
          setDogRelay({ text: last.text, dogSpoke: last.dog_spoke ? true : undefined });
        }
      })
      .catch(() => {});
    familyMessageApi
      .myFamilies()
      .then((res) => {
        const fams = res.families || [];
        setFamFamilies(fams);
        if (fams.length > 0) setFamTarget(fams[0].family_user_id);
      })
      .catch(() => {});
  }, [hydrated, accessToken, user?.role]);

  // 回忆录：进页面拉一次待确认条目；失败静默（该功能不可用不应打扰老人）
  useEffect(() => {
    if (!hydrated || !accessToken || user?.role !== 'elderly') return;
    memoirApi
      .pendingStories()
      .then(setPendingStories)
      .catch(() => {});
  }, [hydrated, accessToken, user?.role]);

  // SSE：家人的留言 / 已读回应 / 小狗传话 实时到达，无需手动刷新
  useServerEvents(
    accessToken,
    (e) => {
      if (e.type === 'dog_relay') {
        setDogRelay({
          text: String(e.text ?? ''),
          relation: e.relation ? String(e.relation) : undefined,
          content: e.content ? String(e.content) : undefined,
          dogSpoke: e.dog_spoke ? true : undefined,
        });
        // 实时收到了，就把库里的记录标记已读，避免下次刷新再补念一次
        if (typeof e.message_id === 'number') {
          familyMessageApi.markRead(e.message_id).catch(() => {});
        }
        return;
      }
      familyMessageApi
        .received()
        .then((res) => {
          setFamInbox(res.inbox || []);
          setFamSent(res.sent || []);
          setFamUnread(res.unread || 0);
        })
        .catch(() => {});
    },
    !!hydrated && user?.role === 'elderly'
  );

  if (!hydrated || !accessToken || user?.role === 'family') {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <p className="text-xl text-gray-600">加载中...</p>
      </div>
    );
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || sending) return;
    setError('');
    const userMsg: Message = {
      id: `u-${Date.now()}`,
      role: 'user',
      content: text.trim(),
      timestamp: Date.now(),
    };
    const aiId = `a-${Date.now()}`;
    // 先放一个空的 AI 气泡，流式增量往里填，实现"边生成边显示"
    setMessages((m) => [
      ...m,
      userMsg,
      { id: aiId, role: 'assistant', content: '', timestamp: Date.now() },
    ]);
    setInput('');
    setSending(true);

    let acc = '';        // 累积的完整回复
    let spoken = 0;      // 已送去合成的字符下标（按句切分）
    let spokeAnything = false;

    // 每凑齐若干句就**逐句**合成并排队播放：第一句一好就出声，
    // 不必等整段生成完再合成（首句出声因此明显提前）
    const SENT_PUNCT = '。！？!?；;\n';
    const speakOne = (sentence: string) => {
      spokeAnything = true;
      speechApi
        .tts(sentence)
        .then((r) => {
          if (!r.audio_url) return;
          enqueueAudio(r.audio_url);
        })
        .catch(() => {
          // 单句合成失败不影响后续句子
        });
    };

    const flushSentences = (final: boolean) => {
      const pending = acc.slice(spoken);
      if (!pending) return;
      // 取到最后一个句末标点；final 时把剩余全部视为完整
      let cut = 0;
      for (let i = 0; i < pending.length; i++) {
        if (SENT_PUNCT.includes(pending[i])) cut = i + 1;
      }
      if (final) cut = pending.length;
      if (cut === 0) return;
      const block = pending.slice(0, cut);
      spoken += cut;
      // 按句末标点切开，逐句送去合成
      for (const s of block.split(/(?<=[。！？!?；;\n])/)) {
        const piece = s.trim();
        if (piece) speakOne(piece);
      }
    };

    try {
      await chatApi.sendStream(text.trim(), {
        onDelta: (t) => {
          acc += t;
          setMessages((m) =>
            m.map((x) => (x.id === aiId ? { ...x, content: acc } : x))
          );
          flushSentences(false);
        },
        onDone: (res) => {
          const reply = res.reply || acc;
          acc = reply;
          setMessages((m) =>
            m.map((x) =>
              x.id === aiId
                ? {
                    ...x,
                    content: reply,
                    emotion: res.emotion,
                    riskLevel: res.risk_level,
                    intent: res.intent,
                    scene: res.scene,
                    topic: res.topic,
                    need: res.need,
                    action: res.action,
                    actionReason: res.action_reason,
                    recalledMemories: res.recalled_memories,
                  }
                : x
            )
          );
          setLastReply(reply);
          setAutoSpoken(spokeAnything);
          if (res.recommendation) {
            setRecommendation(
              typeof res.recommendation === 'string'
                ? { title: '为您推荐', content: res.recommendation }
                : res.recommendation
            );
          }
        },
        onError: (detail) => {
          setError(detail);
          // 去掉没填上内容的空气泡，避免留个空白框
          setMessages((m) => m.filter((x) => !(x.id === aiId && !x.content)));
        },
      });
      flushSentences(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '发送失败，请重试');
      setMessages((m) => m.filter((x) => !(x.id === aiId && !x.content)));
    } finally {
      setSending(false);
    }

    // 生平故事提取是 /chat 的后台任务，稍等片刻再拉一次待确认列表；
    // 失败静默——不能因为回忆录功能让聊天报错。
    window.setTimeout(() => {
      memoirApi
        .pendingStories()
        .then(setPendingStories)
        .catch(() => {});
    }, 3200);
  };

  // 老人对某段往事的处置：确认留档 / 先不用（契约1，只有老人端会调用）
  const handleStoryDecided = async (
    id: number,
    via: 'button' | 'voice',
    action: 'confirm' | 'discard'
  ) => {
    try {
      if (action === 'confirm') {
        await memoirApi.confirmStory(id, via);
      } else {
        await memoirApi.discardStory(id, via);
      }
      setPendingStories((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // 失败就重新同步一次，避免界面与后端不一致
      memoirApi.pendingStories().then(setPendingStories).catch(() => {});
      setError(action === 'confirm' ? '没记上，请再试一次' : '操作没成功，请再试一次');
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  // 老人回应家人留言（标记已读 + 回一个表情）
  const handleFamRead = async (id: number, reaction?: string) => {
    try {
      await familyMessageApi.markRead(id, reaction);
      setFamInbox((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, is_read: true, reaction: reaction ?? m.reaction } : m
        )
      );
      setFamUnread((n) => Math.max(0, n - 1));
    } catch {
      // 静默失败
    }
  };

  // 老人给家人写留言
  const handleFamSend = async (e: FormEvent) => {
    e.preventDefault();
    if (!famTarget || !famContent.trim()) return;
    setSendingFam(true);
    try {
      await familyMessageApi.send(famContent.trim(), famTarget, famCategory);
      setFamContent('');
      const res = await familyMessageApi.received();
      setFamSent(res.sent || []);
    } catch {
      // 静默失败
    } finally {
      setSendingFam(false);
    }
  };

  const handleRecommend = async (type: 'music' | 'story') => {
    setError('');
    try {
      let items: RecommendItem[] = [];
      if (type === 'music') {
        const res = await recommendApi.music(9);
        items = (res.items || []).map((s) => ({
          title: s.title,
          subtitle: s.artist ? `演唱：${s.artist}` : undefined,
          detail: s.reason,
          // 暂无音频源，先跳转音乐平台搜索收听
          searchUrl: `https://y.qq.com/n/ryqq/search?w=${encodeURIComponent(
            `${s.title} ${s.artist || ''}`.trim()
          )}`,
        }));
      } else {
        const res = await recommendApi.story(9);
        items = (res.items || []).map((s) => ({
          title: s.title,
          subtitle: s.length === 'tiny' ? '小故事' : '短故事',
          detail: s.summary,
          speakText: `${s.title}。${s.summary || ''}`,
        }));
      }
      setRecPool(items);
      setRecOffset(0);
      setRecommendation({ kind: type, items: items.slice(0, 3) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '获取推荐失败');
    }
  };

  // 从候选池里轮换展示下一批（「再换一批」）
  const handleRefreshRecommend = () => {
    const kind = recommendation?.kind;
    if (!kind) return;
    if (recPool.length <= 3) {
      handleRecommend(kind);
      return;
    }
    const start = (recOffset + 3) % recPool.length;
    const items = Array.from(
      { length: 3 },
      (_, i) => recPool[(start + i) % recPool.length]
    );
    setRecOffset(start);
    setRecommendation({ kind, items });
  };

  // 小狗传话已由上方气泡念出，不再重复出现在家人留言列表里
  const visibleFamInbox = famInbox.filter((m) => m.category !== 'dog_relay');

  return (
    <div className="max-w-3xl mx-auto px-4 py-4 flex flex-col h-[calc(100vh-72px)]">
      {/* 顶部状态栏 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <h1 className="text-2xl font-bold text-warm-primary">
          💬 {user?.name || user?.username || '您'} 的贴心陪伴
        </h1>
        <div className="flex items-center gap-2">
          <button
            onClick={toggleAutoTTS}
            aria-pressed={autoTTS}
            className="min-h-[48px] px-4 rounded-xl bg-white border-2 border-warm-primary text-warm-primary font-medium"
            title={autoTTS ? '关闭自动语音播报' : '开启自动语音播报'}
          >
            {autoTTS ? '🔊 自动播报' : '🔇 静音'}
          </button>
          <TTSPlayer text={autoTTS ? lastReply : null} autoPlay={!autoSpoken} />
        </div>
      </div>

      {/* 小狗传话：家属让机器狗说的话，实时念给老人听 */}
      {dogRelay && (
        <div className="bg-gradient-to-r from-sky-50 to-indigo-50 border-2 border-indigo-200 rounded-2xl mb-3 p-4">
          <div className="flex items-start gap-3">
            <div className="text-4xl leading-none">🐶</div>
            <div className="flex-1 min-w-0">
              <p className="font-bold text-indigo-700 text-lg">小狗来传话啦</p>
              <p className="text-gray-900 text-xl mt-1 break-words">{dogRelay.text}</p>
              {dogRelay.relation && (
                <p className="text-xs text-gray-500 mt-1">{dogRelay.relation} 的牵挂</p>
              )}
              <div className="mt-2">
                {dogRelay.dogSpoke ? (
                  <p className="text-xs text-indigo-500">🐶 小狗已经把这句话念给您听啦，点下方可再听一遍：</p>
                ) : (
                  <p className="text-xs text-gray-400">正在用语音念给您听…</p>
                )}
                <div className="mt-1">
                  <TTSPlayer text={dogRelay.text} autoPlay={!dogRelay.dogSpoke} />
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setDogRelay(null)}
              className="min-h-[44px] min-w-[44px] rounded-xl bg-white text-gray-500 hover:text-gray-800 text-2xl"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 家人的牵挂（老人 ↔ 家属 双向） */}
      {(famInbox.length > 0 || famFamilies.length > 0) && (
        <div className="bg-gradient-to-r from-rose-50 to-amber-50 border-2 border-rose-200 rounded-2xl mb-3">
          <button
            type="button"
            onClick={() => setFamOpen((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-3"
            aria-expanded={famOpen}
          >
            <span className="font-bold text-gray-800">
              💌 家人的牵挂{famUnread > 0 ? `（${famUnread} 条新）` : ''}
            </span>
            <span className="text-gray-500">{famOpen ? '▲' : '▼'}</span>
          </button>

          {famOpen && (
            <div className="px-4 pb-4 space-y-3">
              {/* 收件箱：家人发给我的 */}
              {visibleFamInbox.length === 0 ? (
                <p className="text-sm text-gray-500">家人还没给您留言</p>
              ) : (
                <ul className="space-y-2">
                  {visibleFamInbox.map((m) => (
                    <li
                      key={m.id}
                      className={`bg-white/80 rounded-xl px-4 py-3 border-2 ${
                        m.is_read ? 'border-warm-light' : 'border-rose-300'
                      }`}
                    >
                      <p className="text-gray-900 text-lg">{m.content}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        {new Date(m.created_at).toLocaleString('zh-CN')}
                        {m.is_read && m.reaction ? ` · 您已回应 ${m.reaction}` : ''}
                      </p>
                      {!m.is_read && (
                        <div className="flex gap-2 mt-2">
                          {['❤️', '😊', '👍'].map((r) => (
                            <button
                              key={r}
                              type="button"
                              onClick={() => handleFamRead(m.id, r)}
                              className="min-h-[44px] min-w-[52px] rounded-xl bg-warm-light hover:bg-warm-primary text-xl"
                              aria-label={`回应 ${r}`}
                            >
                              {r}
                            </button>
                          ))}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}

              {/* 老人给家人留言 */}
              {famFamilies.length > 0 && (
                <div className="bg-white/70 rounded-xl p-3">
                  {!famComposeOpen ? (
                    <button
                      type="button"
                      onClick={() => setFamComposeOpen(true)}
                      className="w-full min-h-[48px] rounded-xl bg-warm-primary text-white font-medium"
                    >
                      ✍️ 给家人写句话
                    </button>
                  ) : (
                    <form onSubmit={handleFamSend} className="space-y-2">
                      {famFamilies.length > 1 && (
                        <select
                          value={famTarget}
                          onChange={(e) => setFamTarget(e.target.value)}
                          className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none bg-white"
                          aria-label="选择家人"
                        >
                          {famFamilies.map((f) => (
                            <option key={f.family_user_id} value={f.family_user_id}>
                              {f.relationship_name || '家人'}
                            </option>
                          ))}
                        </select>
                      )}
                      <div className="flex gap-2 flex-wrap">
                        {MSG_CATEGORIES.map((c) => (
                          <button
                            key={c.value}
                            type="button"
                            onClick={() => setFamCategory(c.value)}
                            className={`min-h-[40px] px-3 rounded-xl text-sm border-2 ${
                              famCategory === c.value
                                ? 'bg-warm-primary text-white border-warm-primary'
                                : 'bg-white text-gray-700 border-warm-light'
                            }`}
                          >
                            {c.emoji} {c.label}
                          </button>
                        ))}
                      </div>
                      <textarea
                        value={famContent}
                        onChange={(e) => setFamContent(e.target.value)}
                        rows={2}
                        placeholder="如：孩子，我挺好的，你们别惦记～"
                        className="w-full px-4 py-3 rounded-2xl border-2 border-warm-light focus:border-warm-primary outline-none resize-none"
                      />
                      <div className="flex gap-2">
                        <button
                          type="submit"
                          disabled={sendingFam || !famContent.trim()}
                          className="min-h-[48px] px-5 rounded-xl bg-warm-primary text-white font-medium disabled:opacity-50"
                        >
                          {sendingFam ? '发送中...' : '发送'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setFamComposeOpen(false)}
                          className="min-h-[48px] px-5 rounded-xl bg-warm-light text-gray-700"
                        >
                          收起
                        </button>
                      </div>
                    </form>
                  )}
                </div>
              )}

              {/* 我发出的留言 */}
              {famSent.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-gray-600 mb-1">我发给家人的</h3>
                  <ul className="space-y-1">
                    {famSent.map((m) => (
                      <li key={m.id} className="bg-white/60 rounded-xl px-3 py-2 text-sm">
                        <span className="text-gray-800">{m.content}</span>
                        <span className="text-gray-500 ml-2">
                          {m.is_read ? '✅ 已看到' : '⏳ 未看到'}
                          {m.reaction ? ` · ${m.reaction}` : ''}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 消息列表 */}
      <div
        ref={listRef}
        className="flex-1 overflow-y-auto bg-warm-light/40 rounded-2xl p-4 mb-3"
      >
        {messages.map((m) => (
          <ChatMessage key={m.id} message={m} />
        ))}
        {sending && (
          <div className="flex justify-start mb-3">
            <div className="bg-white rounded-2xl px-5 py-3 text-gray-500 border border-warm-light">
              🌻 正在思考...
            </div>
          </div>
        )}
      </div>

      {error && (
        <div className="bg-red-50 border-2 border-red-300 text-red-700 rounded-xl px-4 py-2 mb-3">
          {error}
        </div>
      )}

      {/* 回忆录：老人端留档确认卡（契约1，仅老人端出现） */}
      <StoryConfirmCard
        stories={pendingStories}
        onConfirm={(id, via) => handleStoryDecided(id, via, 'confirm')}
        onDiscard={(id, via) => handleStoryDecided(id, via, 'discard')}
      />

      {/* 推荐卡片 */}
      {recommendation && (
        <div className="bg-gradient-to-r from-amber-50 to-orange-50 border-2 border-warm-primary rounded-2xl p-4 mb-3">
          <div className="flex items-start justify-between gap-3">
            <h3 className="font-bold text-warm-dark text-lg mb-1">
              {recommendation.title ||
                (recommendation.kind === 'story'
                  ? '📖 给您推荐这几个故事'
                  : recommendation.kind === 'music'
                    ? '🎵 给您推荐这几首歌'
                    : '💡 为您推荐')}
            </h3>
            <button
              onClick={() => setRecommendation(null)}
              className="min-h-[48px] min-w-[48px] text-gray-400 hover:text-gray-700 text-2xl"
              aria-label="关闭推荐"
            >
              ✕
            </button>
          </div>

          {recommendation.items && recommendation.items.length > 0 ? (
            <>
              <ul className="space-y-2 mt-1">
                {recommendation.items.map((it, i) => (
                  <li key={i} className="bg-white/70 rounded-xl px-4 py-3">
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                      <div className="flex-1 min-w-[180px]">
                        <p className="font-bold text-gray-900 text-lg">{it.title}</p>
                        {it.subtitle && (
                          <p className="text-sm text-gray-500">{it.subtitle}</p>
                        )}
                        {it.detail && <p className="text-gray-700 mt-1">{it.detail}</p>}
                      </div>
                      <div className="flex-shrink-0">
                        {it.speakText ? (
                          <SpeakButton text={it.speakText} label="🔊 听一听" />
                        ) : it.searchUrl ? (
                          <a
                            href={it.searchUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center min-h-[48px] px-4 rounded-xl bg-warm-light hover:bg-warm-primary hover:text-white text-warm-primary font-medium"
                          >
                            🎧 去收听
                          </a>
                        ) : null}
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between gap-2 mt-2 flex-wrap">
                <p className="text-xs text-gray-500">
                  {recommendation.kind === 'story'
                    ? '点「🔊 听一听」，用语音把故事读给您听'
                    : '点「🎧 去收听」，在音乐平台搜索这首歌'}
                </p>
                <button
                  type="button"
                  onClick={handleRefreshRecommend}
                  className="flex-shrink-0 min-h-[40px] px-4 rounded-xl bg-white border-2 border-warm-primary text-warm-primary font-medium text-sm hover:bg-warm-primary hover:text-white"
                >
                  🔄 再换一批
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-gray-700">{recommendation.content}</p>
              {recommendation.url && (
                <a
                  href={recommendation.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block mt-2 text-warm-primary underline font-medium"
                >
                  👉 点击打开
                </a>
              )}
            </>
          )}
        </div>
      )}

      {/* 快捷推荐 + 拍照看看 */}
      <div className="flex gap-2 mb-3">
        <LargeButton variant="secondary" onClick={() => handleRecommend('music')} className="flex-1">
          🎵 听首歌
        </LargeButton>
        <LargeButton variant="secondary" onClick={() => handleRecommend('story')} className="flex-1">
          📖 听故事
        </LargeButton>
        <LargeButton variant="secondary" onClick={() => setCameraOpen(true)} className="flex-1">
          🎥 指挥小狗
        </LargeButton>
      </div>

      {/* 视频动作面板：实时姿势识别 → 直接控制机器狗 */}
      {cameraOpen && (
        <CameraPanel
          onClose={() => setCameraOpen(false)}
          onVoice={(text) => sendMessage(text)}
        />
      )}

      {/* 常用短语：老人打字不便，一点即发 */}
      <div className="flex gap-2 mb-3 overflow-x-auto pb-1">
        {QUICK_PHRASES.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => sendMessage(p)}
            disabled={sending}
            className="flex-shrink-0 min-h-[48px] px-4 rounded-2xl bg-white border-2 border-warm-light hover:border-warm-primary text-gray-700 text-base disabled:opacity-50"
          >
            {p}
          </button>
        ))}
      </div>

      {/* 输入区：输入框 + 大🎤按钮 */}
      <form onSubmit={handleSubmit} className="flex items-end gap-3">
        <div className="flex-1">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage(input);
              }
            }}
            placeholder="想说什么都可以..."
            rows={2}
            className="w-full px-4 py-3 rounded-2xl border-2 border-warm-primary focus:border-warm-dark outline-none resize-none text-lg"
            aria-label="聊天输入框"
          />
        </div>
        <div className="flex flex-col items-center gap-1">
          <VoiceRecorder
            onRecognized={(text) => sendMessage(text)}
            onError={(msg) => setError(msg)}
          />
          <span className="text-xs text-gray-500">按住说话</span>
          <Link
            href="/call"
            className="text-xs font-bold text-warm-dark hover:text-warm-primary underline"
            title="进入语音通话：像打电话一样聊天，可以说方言"
          >
            📞 打电话
          </Link>
        </div>
        <LargeButton type="submit" size="lg" disabled={sending || !input.trim()}>
          发送
        </LargeButton>
      </form>
    </div>
  );
}

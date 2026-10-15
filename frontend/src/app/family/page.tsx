'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { familyApi, dogApi, ApiError, ElderlyItem, EmotionRecord, MemoryItem, FamilyAlert, EmotionTrendDay, FamilyMessageItem, familyMessageApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { useServerEvents } from '@/lib/events';
import { LargeButton } from '@/components/LargeButton';
import { EmotionChart, EMOTION_LABEL } from '@/components/EmotionChart';
import { EmotionTrendChart } from '@/components/EmotionTrendChart';
import { EmotionInsights } from '@/components/EmotionInsights';
import { MemoryList } from '@/components/MemoryList';
import { PersonNetwork } from '@/components/PersonNetwork';
import { FamilyMemoirPanel } from '@/components/FamilyMemoirPanel';
import { extractPersons } from '@/lib/personExtract';

const MSG_CATEGORIES = [
  { value: 'greeting', label: '问候', emoji: '👋' },
  { value: 'care', label: '关心', emoji: '🤗' },
  { value: 'remind', label: '叮嘱', emoji: '📌' },
  { value: 'miss', label: '想念', emoji: '💝' },
];

/** 日报 content（JSON）的结构 */
interface DigestStats {
  rounds: number;
  main_emotion: string;
  main_emotion_label: string;
  topics: { topic: string; count: number }[];
  time_range: string;
}
/** 日报里的回忆录增量（只含老人愿意分享的条目） */
interface DigestMemoir {
  today: number;
  week: number;
  total: number;
}
interface DigestPayload {
  date?: string;
  summary?: string;
  stats?: DigestStats;
  memoir?: DigestMemoir;
}

function parseDigest(content: string): DigestPayload | null {
  try {
    const data = JSON.parse(content);
    if (data && typeof data.summary === 'string') return data as DigestPayload;
  } catch {
    // 非 JSON（旧格式纯文本）
  }
  return null;
}

/** 老人当前表情（来自摄像头表情识别的 SSE 实时推送） */
interface LiveEmotion {
  emotion: string;
  label: string;
  score: number;
  ts: number;
}

const EMOTION_EMOJI: Record<string, string> = {
  happy: '😊', sad: '😢', angry: '😠', fear: '😨',
  disgust: '🤢', surprise: '😲', neutral: '😌',
};

/** 每日陪伴日报卡片（系统推送，区别于普通留言） */
function DigestCard({ msg, onRead }: { msg: FamilyMessageItem; onRead: (id: number) => void }) {
  const digest = parseDigest(msg.content);
  if (!digest) {
    return (
      <li className="bg-warm-light/40 rounded-xl px-4 py-3 border-2 border-warm-light">
        <p className="text-gray-900">{msg.content}</p>
        <p className="text-sm text-gray-500 mt-1">
          {new Date(msg.created_at).toLocaleString('zh-CN')}
        </p>
      </li>
    );
  }
  const s = digest.stats;
  const m = digest.memoir;
  return (
    <li
      className={`rounded-2xl px-4 py-4 border-2 ${
        msg.is_read ? 'bg-warm-light/40 border-warm-light' : 'bg-amber-50 border-amber-300'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">📅</span>
        <span className="font-bold text-gray-900">今日陪伴日报</span>
        {digest.date && <span className="text-sm text-gray-500">{digest.date}</span>}
        {!msg.is_read && (
          <span className="ml-auto text-xs bg-rose-500 text-white px-2 py-0.5 rounded-full">新</span>
        )}
      </div>
      {s && (
        <div className="flex flex-wrap gap-2 mb-2">
          {s.rounds > 0 && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              💬 {s.rounds} 轮
            </span>
          )}
          {s.main_emotion_label && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              😊 {s.main_emotion_label}
            </span>
          )}
          {s.topics?.length > 0 && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              🏷️ {s.topics.map((t) => t.topic).join('、')}
            </span>
          )}
          {s.time_range && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              🕐 {s.time_range}
            </span>
          )}
        </div>
      )}
      {/* 回忆录增量：只包含老人愿意分享的条目，创伤类 private 不进计数 */}
      {m && (m.today > 0 || m.week > 0) && (
        <div className="flex flex-wrap gap-2 mb-2">
          {m.today > 0 && (
            <span className="text-xs bg-emerald-50 border border-emerald-200 text-emerald-700 rounded-full px-2 py-1">
              📖 {m.today === 1 ? '今天留下了一段新回忆' : `今天留下了 ${m.today} 段新回忆`}
            </span>
          )}
          {m.week > 0 && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              本周新增 {m.week} 段
            </span>
          )}
          {m.total > 0 && (
            <span className="text-xs bg-white border border-warm-light rounded-full px-2 py-1">
              共 {m.total} 段
            </span>
          )}
        </div>
      )}
      <p className="text-gray-900 leading-relaxed whitespace-pre-line">{digest.summary}</p>
      <div className="flex items-center justify-between mt-2">
        <p className="text-sm text-gray-500">{new Date(msg.created_at).toLocaleString('zh-CN')}</p>
        {!msg.is_read && (
          <button
            type="button"
            onClick={() => onRead(msg.id)}
            className="text-sm text-warm-primary underline min-h-[36px] px-2"
          >
            标为已读
          </button>
        )}
      </div>
    </li>
  );
}

export default function FamilyPage() {
  const router = useRouter();
  const { user, accessToken } = useAuthStore();
  const [elderlyList, setElderlyList] = useState<ElderlyItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [records, setRecords] = useState<EmotionRecord[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [trend, setTrend] = useState<EmotionTrendDay[]>([]);
  const [days, setDays] = useState<7 | 30>(7);
  const [alerts, setAlerts] = useState<FamilyAlert[]>([]);
  const [msgTarget, setMsgTarget] = useState<string>('');
  const [msgContent, setMsgContent] = useState('');
  const [msgCategory, setMsgCategory] = useState('greeting');
  const [sentMsgs, setSentMsgs] = useState<FamilyMessageItem[]>([]);
  const [inboxMsgs, setInboxMsgs] = useState<FamilyMessageItem[]>([]);
  const [sendingMsg, setSendingMsg] = useState(false);
  const [ackingId, setAckingId] = useState<number | null>(null);
  const [alertElderly, setAlertElderly] = useState<string>('all');
  const [selectedPerson, setSelectedPerson] = useState<string | null>(null);
  const [tab, setTab] = useState<'emotion' | 'memories' | 'memoir'>('emotion');
  const [bindUsername, setBindUsername] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  // 老人实时表情（摄像头表情识别推送）：elderly_id → 最新一次识别
  const [liveEmotions, setLiveEmotions] = useState<Record<string, LiveEmotion>>({});

  // 让小狗传话（仅传话，不指挥动作）
  const RELATIONS = ['女儿', '儿子', '孙女', '孙子', '外孙女', '外孙', '儿媳', '女婿'];
  const [relayRelation, setRelayRelation] = useState('女儿');
  const [relayCustom, setRelayCustom] = useState('');
  const [relayContent, setRelayContent] = useState('');
  const [sendingRelay, setSendingRelay] = useState(false);
  const [relayMsg, setRelayMsg] = useState('');

  useEffect(() => {
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated && !accessToken) router.push('/login');
  }, [hydrated, accessToken, router]);

  // 老人不能进家属看板，重定向回聊天页
  useEffect(() => {
    if (hydrated && accessToken && user?.role === 'elderly') {
      router.push('/');
    }
  }, [hydrated, accessToken, user?.role, router]);

  useEffect(() => {
    if (!hydrated || !accessToken || user?.role !== 'family') return;
    loadList();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, accessToken, user?.role]);

  const loadSent = async (elderlyId: string) => {
    if (!elderlyId) return;
    try {
      const res = await familyApi.sentMessages(elderlyId);
      setSentMsgs(res.sent || []);
      setInboxMsgs(res.inbox || []);
    } catch {
      setSentMsgs([]);
      setInboxMsgs([]);
    }
  };

  const loadList = async () => {
    try {
      const res = await familyApi.list();
      const list = Array.isArray(res) ? res : res.elderly || [];
      setElderlyList(list);
      if (list.length > 0 && !msgTarget) {
        setMsgTarget(list[0].elderly_id);
        loadSent(list[0].elderly_id);
      }
    } catch {
      setElderlyList([]);
    }
    // 告警与各老人绑定状态无关，单独加载
    try {
      const a = await familyApi.alerts();
      setAlerts(a || []);
    } catch {
      setAlerts([]);
    }
  };

  // SSE：老人发来的留言 / 回应 / 实时表情识别结果，无需手动刷新
  useServerEvents(
    accessToken,
    (e) => {
      if (e.type === 'face_emotion') {
        const uid = String(e.user_id ?? '');
        const emotion = String(e.emotion ?? '');
        if (uid && emotion) {
          setLiveEmotions((prev) => ({
            ...prev,
            [uid]: {
              emotion,
              label: String(e.emotion_label ?? emotion),
              score: Number(e.score ?? 0),
              ts: Date.now(),
            },
          }));
          // 正在看这位老人的情绪历史时，把新识别实时补进列表
          if (selectedId === uid) {
            setRecords((prev) => [
              { emotion, intensity: Number(e.score ?? 0) / 100, created_at: String(e.created_at ?? '') },
              ...prev,
            ]);
          }
        }
        return;
      }
      if (msgTarget) loadSent(msgTarget);
    },
    !!hydrated && user?.role === 'family'
  );

  if (!hydrated || !accessToken) return null;

  if (user?.role !== 'family') {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 text-center">
        <p className="text-xl text-gray-600 mb-4">👨‍👩‍👧 家属看板</p>
        <p className="text-gray-500">此页面仅供家属账号使用</p>
      </div>
    );
  }

  const handleBind = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');
    if (!bindUsername.trim() || !inviteCode.trim()) {
      setError('请输入老人用户名和邀请码');
      return;
    }
    setLoading(true);
    try {
      await familyApi.bind(bindUsername.trim(), inviteCode.trim());
      setMessage('✅ 绑定成功！');
      setBindUsername('');
      setInviteCode('');
      await loadList();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '绑定失败');
    } finally {
      setLoading(false);
    }
  };

  const handleViewEmotion = async (elderlyId: string) => {
    setSelectedId(elderlyId);
    setTab('emotion');
    loadTrend(elderlyId, days);
    try {
      const res = await familyApi.emotion(elderlyId, 50);
      setRecords(res.records || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载情绪记录失败');
    }
  };

  const handleViewMemories = async (elderlyId: string) => {
    setSelectedId(elderlyId);
    setSelectedPerson(null);
    setTab('memories');
    try {
      const res = await familyApi.memories(elderlyId);
      setMemories(res.memories || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载记忆失败');
    }
  };

  // 回忆录是只读的（外加补照片），数据在面板内部自取，这里只切 tab
  const handleViewMemoir = (elderlyId: string) => {
    setSelectedId(elderlyId);
    setSelectedPerson(null);
    setTab('memoir');
  };

  const loadTrend = async (elderlyId: string, d: 7 | 30) => {
    try {
      const t = await familyApi.emotionTrend(elderlyId, d);
      setTrend(t || []);
    } catch {
      setTrend([]);
    }
  };

  const handleDaysChange = (d: 7 | 30) => {
    setDays(d);
    if (selectedId) loadTrend(selectedId, d);
  };

  const handleAck = async (alertId: number) => {
    setAckingId(alertId);
    try {
      await familyApi.ackAlert(alertId);
      setAlerts((prev) =>
        prev.map((a) => (a.id === alertId ? { ...a, is_acknowledged: true } : a))
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '确认失败');
    } finally {
      setAckingId(null);
    }
  };

  const handleSendMsg = async (e: FormEvent) => {
    e.preventDefault();
    if (!msgTarget || !msgContent.trim()) return;
    setSendingMsg(true);
    try {
      await familyApi.sendMessage(msgTarget, msgContent.trim(), msgCategory);
      setMsgContent('');
      await loadSent(msgTarget);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '发送失败');
    } finally {
      setSendingMsg(false);
    }
  };

  const handleRelay = async (e: FormEvent) => {
    e.preventDefault();
    const relation =
      relayRelation === '__custom__' ? relayCustom.trim() : relayRelation;
    if (!msgTarget || !relation || !relayContent.trim()) return;
    setSendingRelay(true);
    setRelayMsg('');
    try {
      const res = await dogApi.relay(msgTarget, relation, relayContent.trim());
      setRelayContent('');
      setRelayMsg(`🐶 ${res.message}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '传话失败');
    } finally {
      setSendingRelay(false);
    }
  };

  const handleMsgRead = async (id: number, reaction?: string) => {
    try {
      await familyMessageApi.markRead(id, reaction);
      setInboxMsgs((prev) =>
        prev.map((m) =>
          m.id === id ? { ...m, is_read: true, reaction: reaction ?? m.reaction } : m
        )
      );
    } catch {
      // 静默失败
    }
  };

  const elderNameOf = (id?: string) =>
    elderlyList.find((e) => e.elderly_id === id)?.name || '老人';

  const renderAlert = (a: FamilyAlert) => {
    const sev =
      a.severity === 'high'
        ? 'border-red-400 bg-red-50'
        : 'border-amber-300 bg-amber-50';
    return (
      <div key={a.id} className={`rounded-2xl border-2 p-4 ${sev}`}>
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <p className="font-bold text-lg text-gray-900">{a.title}</p>
            <p className="text-gray-700 mt-1">{a.detail}</p>
            <p className="text-sm text-gray-500 mt-1">
              👴 {elderNameOf(a.elderly_user_id)} ·{' '}
              {new Date(a.created_at).toLocaleString('zh-CN')}
            </p>
          </div>
          <div>
            {a.is_acknowledged ? (
              <span className="inline-flex items-center px-3 py-2 rounded-xl bg-green-100 text-green-700 font-medium">
                ✓ 已关注
              </span>
            ) : (
              <LargeButton
                className="px-3 min-h-[40px] text-sm"
                disabled={ackingId === a.id}
                onClick={() => handleAck(a.id)}
              >
                {ackingId === a.id ? '处理中...' : '我已关注'}
              </LargeButton>
            )}
          </div>
        </div>
      </div>
    );
  };

  // 告警：按老人筛选 + 拆分「待关注 / 已处理」
  const filteredAlerts = alerts.filter(
    (a) => alertElderly === 'all' || a.elderly_user_id === alertElderly
  );
  const pendingAlerts = filteredAlerts.filter((a) => !a.is_acknowledged);
  const ackedAlerts = filteredAlerts.filter((a) => a.is_acknowledged);

  const selectedElderlyName = elderNameOf(selectedId ?? undefined);
  const persons = extractPersons(memories);
  const visibleMemories = selectedPerson
    ? persons.find((p) => p.key === selectedPerson)?.memories || []
    : memories;

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-6">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-600">陪伴状态中心</p>
          <h1 className="text-3xl font-bold text-gray-900 mt-1">家属看板</h1>
          <p className="text-gray-500 mt-1">快速了解家人的近况，把关心变成及时的陪伴。</p>
        </div>
        <div className="rounded-full bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700">
          ● 系统运行正常
        </div>
      </div>

      {/* 可视化总览：先用当前接口状态承载信息架构，后续逐项替换为实时指标。 */}
      <section className="rounded-3xl bg-slate-900 p-5 sm:p-7 text-white shadow-xl">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p className="text-sm text-slate-300">今日陪伴概览</p>
            <h2 className="text-2xl font-bold mt-1">{elderlyList.length ? '家人的状态，值得被看见' : '开始建立陪伴档案'}</h2>
          </div>
          <div className="text-right">
            <p className="text-3xl font-bold text-amber-300">{pendingAlerts.length}</p>
            <p className="text-xs text-slate-300">待关注提醒</p>
          </div>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
          {[
            { label: '绑定家人', value: elderlyList.length, unit: '位', color: 'text-cyan-300' },
            { label: '情绪趋势', value: records.length ? '稳定' : '待采集', unit: '', color: 'text-emerald-300' },
            { label: '重要记忆', value: memories.length, unit: '条', color: 'text-violet-300' },
            { label: '家庭互动', value: inboxMsgs.length + sentMsgs.length, unit: '次', color: 'text-amber-300' },
          ].map((item) => (
            <div key={item.label} className="rounded-2xl bg-white/10 p-4 backdrop-blur-sm">
              <p className="text-sm text-slate-300">{item.label}</p>
              <p className={`text-2xl font-bold mt-2 ${item.color}`}>{item.value}<span className="text-sm ml-1 font-medium">{item.unit}</span></p>
            </div>
          ))}
        </div>
      </section>

      {/* 家人实时情绪：老人端开着「表情识别」时，这里实时刷新 */}
      {elderlyList.some((e) => liveEmotions[e.elderly_id]) && (
        <section className="rounded-2xl bg-white border-2 border-emerald-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h2 className="text-xl font-bold text-gray-900">😊 家人实时情绪</h2>
              <p className="text-sm text-gray-500 mt-1">
                老人端摄像头表情识别开启时，情绪状态实时同步
              </p>
            </div>
            <span className="flex items-center gap-1 text-xs font-semibold text-emerald-600">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" /> 实时
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {elderlyList
              .filter((e) => liveEmotions[e.elderly_id])
              .map((e) => {
                const live = liveEmotions[e.elderly_id];
                const negative = ['sad', 'angry', 'fear', 'disgust'].includes(live.emotion);
                return (
                  <div
                    key={e.elderly_id}
                    className={`rounded-xl p-4 border-2 ${
                      negative ? 'bg-amber-50 border-amber-300' : 'bg-emerald-50 border-emerald-200'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span className="text-4xl leading-none">
                        {EMOTION_EMOJI[live.emotion] ?? '🙂'}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="font-bold text-gray-900">
                          {e.name || e.username}
                        </p>
                        <p className="text-gray-700">
                          {live.label} · 置信度 {Math.round(live.score)}%
                        </p>
                        <p className="text-xs text-gray-500 mt-0.5">
                          更新于 {new Date(live.ts).toLocaleTimeString('zh-CN')}
                          {negative && ' · 建议打个电话关心一下'}
                        </p>
                      </div>
                    </div>
                  </div>
                );
              })}
          </div>
        </section>
      )}

      <section className="grid lg:grid-cols-[1.35fr_1fr] gap-5">
        <div className="rounded-2xl bg-white border border-slate-200 p-5 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-xl font-bold text-gray-900">陪伴能力地图</h2>
              <p className="text-sm text-gray-500 mt-1">核心能力建设进度</p>
            </div>
            <span className="text-sm font-semibold text-amber-600">8 项能力</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              ['画像', '已建立', 'bg-amber-50 text-amber-700', '👤'],
              ['短期记忆', '实时', 'bg-cyan-50 text-cyan-700', '◷'],
              ['长期记忆', '持续积累', 'bg-violet-50 text-violet-700', '✦'],
              ['情绪分析', '趋势跟踪', 'bg-emerald-50 text-emerald-700', '⌁'],
              ['安全策略', pendingAlerts.length ? '需关注' : '运行中', pendingAlerts.length ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700', '⚠'],
              ['内容推荐', '个性化', 'bg-orange-50 text-orange-700', '♫'],
              ['家庭端', '已连接', 'bg-blue-50 text-blue-700', '⌂'],
              ['定时任务', '规划中', 'bg-slate-100 text-slate-700', '◫'],
            ].map(([name, status, classes, icon]) => (
              <div key={name} className={`rounded-xl p-3 ${classes}`}>
                <div className="flex items-center justify-between"><span className="text-xl">{icon}</span><span className="text-xs font-bold">{status}</span></div>
                <p className="font-semibold mt-2">{name}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200 p-5 shadow-sm">
          <div className="flex items-center justify-between">
            <div><h2 className="text-xl font-bold text-gray-900">近 7 日情绪</h2><p className="text-sm text-gray-500 mt-1">情绪记录可视化预览</p></div>
            <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700">平稳</span>
          </div>
          <div className="h-40 flex items-end gap-2 mt-7 px-2">
            {[42, 58, 48, 68, 55, 74, 63].map((height, index) => (
              <div key={index} className="flex-1 flex flex-col items-center gap-2">
                <div className="w-full rounded-t-lg bg-gradient-to-t from-cyan-500 to-emerald-300" style={{ height: `${height}%` }} />
                <span className="text-xs text-gray-400">{['一','二','三','四','五','六','日'][index]}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between text-sm"><span className="text-gray-500">平均情绪强度</span><strong className="text-emerald-600">68%</strong></div>
        </div>
      </section>

      {/* 绑定老人 */}
      <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">➕ 绑定老人</h2>
        <form onSubmit={handleBind} className="space-y-4">
          <div>
            <label htmlFor="bind-username" className="block mb-1 font-medium text-gray-700">
              老人用户名
            </label>
            <input
              id="bind-username"
              type="text"
              value={bindUsername}
              onChange={(e) => setBindUsername(e.target.value)}
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
              placeholder="老人注册时用的用户名"
            />
          </div>
          <div>
            <label htmlFor="bind-code" className="block mb-1 font-medium text-gray-700">
              邀请码
            </label>
            <input
              id="bind-code"
              type="text"
              value={inviteCode}
              onChange={(e) => setInviteCode(e.target.value)}
              className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
              placeholder="老人账号生成的邀请码"
            />
          </div>
          {error && (
            <div className="bg-red-50 border-2 border-red-300 text-red-700 rounded-xl px-4 py-2">
              {error}
            </div>
          )}
          {message && (
            <div className="bg-green-50 border-2 border-green-300 text-green-700 rounded-xl px-4 py-2">
              {message}
            </div>
          )}
          <LargeButton type="submit" size="lg" disabled={loading}>
            {loading ? '绑定中...' : '绑定'}
          </LargeButton>
        </form>
      </section>

      {/* 老人列表 */}
      <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-4">
          👴 已绑定的老人（{elderlyList.length}）
        </h2>
        {elderlyList.length === 0 ? (
          <p className="text-gray-500">还没有绑定老人，请先绑定</p>
        ) : (
          <ul className="space-y-3">
            {elderlyList.map((e) => (
              <li
                key={e.elderly_id}
                className="flex items-center justify-between bg-warm-light/40 rounded-xl p-4 gap-3 flex-wrap"
              >
                <div>
                  <p className="font-bold text-lg text-gray-900">
                    {e.name || e.username}
                  </p>
                  <p className="text-sm text-gray-500">@{e.username}</p>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <LargeButton
                    variant={selectedId === e.elderly_id && tab === 'emotion' ? 'primary' : 'secondary'}
                    onClick={() => handleViewEmotion(e.elderly_id)}
                  >
                    📊 情绪
                  </LargeButton>
                  <LargeButton
                    variant={selectedId === e.elderly_id && tab === 'memories' ? 'primary' : 'secondary'}
                    onClick={() => handleViewMemories(e.elderly_id)}
                  >
                    🧠 记忆
                  </LargeButton>
                  <LargeButton
                    variant={selectedId === e.elderly_id && tab === 'memoir' ? 'primary' : 'secondary'}
                    onClick={() => handleViewMemoir(e.elderly_id)}
                  >
                    📖 回忆录
                  </LargeButton>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* 给家人留句话（家属 → 老人 双向互动） */}
      {elderlyList.length > 0 && (
        <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-1">💌 给家人留句话</h2>
          <p className="text-sm text-gray-500 mb-4">
            写下问候或叮嘱，老人打开 App 就能看到，还能回您一个 ❤️
          </p>
          <form onSubmit={handleSendMsg} className="space-y-3">
            {elderlyList.length > 1 && (
              <select
                value={msgTarget}
                onChange={(e) => {
                  setMsgTarget(e.target.value);
                  loadSent(e.target.value);
                }}
                className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none bg-white"
                aria-label="选择老人"
              >
                {elderlyList.map((e) => (
                  <option key={e.elderly_id} value={e.elderly_id}>
                    {e.name || e.username}
                  </option>
                ))}
              </select>
            )}
            <div className="flex gap-2 flex-wrap">
              {MSG_CATEGORIES.map((c) => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setMsgCategory(c.value)}
                  className={`min-h-[40px] px-3 rounded-xl text-sm border-2 ${
                    msgCategory === c.value
                      ? 'bg-warm-primary text-white border-warm-primary'
                      : 'bg-white text-gray-700 border-warm-light'
                  }`}
                >
                  {c.emoji} {c.label}
                </button>
              ))}
            </div>
            <textarea
              value={msgContent}
              onChange={(e) => setMsgContent(e.target.value)}
              rows={2}
              placeholder="如：妈，天冷了记得加衣裳，我周末去看您～"
              className="w-full px-4 py-3 rounded-2xl border-2 border-warm-light focus:border-warm-primary outline-none resize-none"
            />
            <LargeButton type="submit" disabled={sendingMsg || !msgContent.trim()}>
              {sendingMsg ? '发送中...' : '发送给TA'}
            </LargeButton>
          </form>

          {inboxMsgs.length > 0 && (
            <div className="mt-4">
              <h3 className="font-medium text-gray-700 mb-2">家人和系统消息</h3>
              <ul className="space-y-2">
                {inboxMsgs.map((m) =>
                  m.category === 'digest' ? (
                    <DigestCard key={m.id} msg={m} onRead={(id) => handleMsgRead(id)} />
                  ) : (
                    <li
                      key={m.id}
                      className={`rounded-xl px-4 py-3 border-2 ${
                        m.is_read
                          ? 'bg-warm-light/40 border-warm-light'
                          : 'bg-rose-50 border-rose-300'
                      }`}
                    >
                      <p className="text-gray-900">{m.content}</p>
                      <p className="text-sm text-gray-500 mt-1">
                        {new Date(m.created_at).toLocaleString('zh-CN')}
                        {m.is_read && m.reaction ? ` · 您已回应 ${m.reaction}` : ''}
                      </p>
                      {!m.is_read && (
                        <div className="flex gap-2 mt-2">
                          {['❤️', '😊', '👍'].map((r) => (
                            <button
                              key={r}
                              type="button"
                              onClick={() => handleMsgRead(m.id, r)}
                              className="min-h-[40px] min-w-[48px] rounded-xl bg-warm-light hover:bg-warm-primary text-lg"
                              aria-label={`回应 ${r}`}
                            >
                              {r}
                            </button>
                          ))}
                        </div>
                      )}
                    </li>
                  )
                )}
              </ul>
            </div>
          )}

          {sentMsgs.length > 0 && (
            <div className="mt-4">
              <h3 className="font-medium text-gray-700 mb-2">我发出的留言</h3>
              <ul className="space-y-2">
                {sentMsgs.map((m) => (
                  <li key={m.id} className="bg-warm-light/40 rounded-xl px-4 py-3">
                    <p className="text-gray-900">{m.content}</p>
                    <p className="text-sm text-gray-500 mt-1">
                      {new Date(m.created_at).toLocaleString('zh-CN')} ·{' '}
                      {m.is_read
                        ? `✅ 老人已看到${m.reaction ? ` · 回应 ${m.reaction}` : ''}`
                        : '⏳ 老人还没看到'}
                    </p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}

      {/* 让小狗传话（家属端：仅传话，不指挥动作） */}
      {elderlyList.length > 0 && (
        <section className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-1">🐶 让小狗传话</h2>
          <p className="text-sm text-gray-500 mb-4">
            写一句话，小狗会在老人身边念出来。例如选「女儿」、写「记得按时吃药」，
            小狗就会说「女儿提醒您：记得按时吃药」。仅传话，不会指挥小狗做动作。
          </p>
          <form onSubmit={handleRelay} className="space-y-3">
            {elderlyList.length > 1 && (
              <select
                value={msgTarget}
                onChange={(e) => {
                  setMsgTarget(e.target.value);
                  loadSent(e.target.value);
                }}
                className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none bg-white"
                aria-label="选择老人"
              >
                {elderlyList.map((e) => (
                  <option key={e.elderly_id} value={e.elderly_id}>
                    {e.name || e.username}
                  </option>
                ))}
              </select>
            )}
            <div className="flex gap-2 flex-wrap">
              {RELATIONS.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRelayRelation(r)}
                  className={`min-h-[40px] px-3 rounded-xl text-sm border-2 ${
                    relayRelation === r
                      ? 'bg-warm-primary text-white border-warm-primary'
                      : 'bg-white text-gray-700 border-warm-light'
                  }`}
                >
                  {r}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setRelayRelation('__custom__')}
                className={`min-h-[40px] px-3 rounded-xl text-sm border-2 ${
                  relayRelation === '__custom__'
                    ? 'bg-warm-primary text-white border-warm-primary'
                    : 'bg-white text-gray-700 border-warm-light'
                }`}
              >
                其他
              </button>
            </div>
            {relayRelation === '__custom__' && (
              <input
                value={relayCustom}
                onChange={(e) => setRelayCustom(e.target.value)}
                placeholder="如：小妹 / 护工阿姨"
                className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none"
              />
            )}
            <textarea
              value={relayContent}
              onChange={(e) => setRelayContent(e.target.value)}
              rows={2}
              placeholder="要传的话，如：记得按时吃药 / 今天降温多穿点"
              className="w-full px-4 py-3 rounded-2xl border-2 border-warm-light focus:border-warm-primary outline-none resize-none"
            />
            <LargeButton type="submit" disabled={sendingRelay || !relayContent.trim()}>
              {sendingRelay ? '小狗跑腿中...' : '🐶 让小狗去说'}
            </LargeButton>
            {relayMsg && (
              <div className="bg-green-50 border-2 border-green-300 text-green-700 rounded-xl px-4 py-2">
                {relayMsg}
              </div>
            )}
          </form>
        </section>
      )}

      {/* 情绪告警（跨所有绑定老人） */}
      {alerts.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-xl font-bold text-gray-900">
              ⚠️ 情绪告警（{pendingAlerts.length} 条待关注）
            </h2>
            {elderlyList.length > 1 && (
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => setAlertElderly('all')}
                  className={`px-3 py-1 rounded-lg text-sm border-2 ${
                    alertElderly === 'all'
                      ? 'bg-warm-primary text-white border-warm-primary'
                      : 'bg-white text-gray-700 border-warm-light'
                  }`}
                >
                  全部
                </button>
                {elderlyList.map((e) => (
                  <button
                    key={e.elderly_id}
                    onClick={() => setAlertElderly(e.elderly_id)}
                    className={`px-3 py-1 rounded-lg text-sm border-2 ${
                      alertElderly === e.elderly_id
                        ? 'bg-warm-primary text-white border-warm-primary'
                        : 'bg-white text-gray-700 border-warm-light'
                    }`}
                  >
                    {e.name || e.username}
                  </button>
                ))}
              </div>
            )}
          </div>

          {pendingAlerts.length === 0 ? (
            <p className="text-gray-500">没有待关注的告警 🎉</p>
          ) : (
            <div className="space-y-3">{pendingAlerts.map((a) => renderAlert(a))}</div>
          )}

          {ackedAlerts.length > 0 && (
            <details className="bg-white rounded-2xl border-2 border-warm-light p-4">
              <summary className="cursor-pointer select-none font-medium text-gray-700">
                ✅ 已处理的告警（{ackedAlerts.length}）
              </summary>
              <div className="space-y-3 mt-3">
                {ackedAlerts.map((a) => renderAlert(a))}
              </div>
            </details>
          )}
        </section>
      )}

      {/* 选中老人的情绪历史 */}
      {selectedId !== null && tab === 'emotion' && (
        <section className="space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h2 className="text-xl font-bold text-gray-900">
              📈 {selectedElderlyName} 的情绪历史
            </h2>
            <div className="flex items-center gap-2">
              {([7, 30] as const).map((d) => (
                <LargeButton
                  key={d}
                  variant={days === d ? 'primary' : 'secondary'}
                  className="px-3 min-h-[40px] text-sm"
                  onClick={() => handleDaysChange(d)}
                >
                  近{d}天
                </LargeButton>
              ))}
            </div>
          </div>
          <EmotionTrendChart trend={trend} />
          <EmotionInsights records={records} />
          <EmotionChart records={records} />
          <div className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
            {records.length === 0 ? (
              <p className="text-gray-500">暂无情绪记录</p>
            ) : (
              <ul className="space-y-2">
                {[...records]
                  .sort(
                    (a, b) =>
                      new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
                  )
                  .map((r, i) => (
                    <li
                      key={i}
                      className="flex items-center justify-between bg-warm-light/40 rounded-xl px-4 py-3"
                    >
                      <span className="font-medium text-gray-900">
                        {EMOTION_LABEL[r.emotion] || r.emotion} · 强度 {Math.round(r.intensity * 100)}%
                      </span>
                      <span className="text-sm text-gray-500">
                        {new Date(r.created_at).toLocaleString('zh-CN')}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {/* 选中老人的记忆 */}
      {selectedId !== null && tab === 'memories' && (
        <section className="space-y-4">
          <h2 className="text-xl font-bold text-gray-900">
            🧠 {selectedElderlyName} 的记忆
          </h2>
          <PersonNetwork
            persons={persons}
            centerLabel={selectedElderlyName}
            selected={selectedPerson}
            onSelect={(p) =>
              setSelectedPerson(selectedPerson === p.key ? null : p.key)
            }
          />
          {selectedPerson && (
            <p className="text-sm text-gray-600">
              正在查看「{selectedPerson}」相关的记忆，点上方人物可取消筛选
            </p>
          )}
          <div className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-6">
            <MemoryList memories={visibleMemories} />
          </div>
        </section>
      )}

      {/* 选中老人的回忆录（只读 + 补照片） */}
      {selectedId !== null && tab === 'memoir' && (
        <FamilyMemoirPanel elderlyId={selectedId} elderlyName={selectedElderlyName} />
      )}
    </div>
  );
}

'use client';

import { useAuthStore } from '@/stores/auth';

const BASE_URL = '/api/v1';

/**
 * 流式接口的基址：聊天必须**直连后端**，不能走 Next 的 rewrites。
 *
 * Next 的 rewrite 会把响应整段缓冲：实测服务端 2.1s 开始出字、2.3s 生成完，
 * 但经 3000 端口拿到第一个 delta 已经是 2.5s（= 整段结束），长回复要等
 * 四五秒才一次性蹦出来，老人体感"特别慢"。浏览器直连 8000 才是真流式。
 *
 * - 开发/局域网：默认 `协议//当前主机:8000`，可用 NEXT_PUBLIC_API_PORT 改；
 * - 同域部署：设 `NEXT_PUBLIC_SSE_BASE=''`，走同源（Nginx 需关闭该路径的缓冲）。
 */
function resolveStreamBase(): string {
  if (typeof window === 'undefined') return '';
  const cfg = process.env.NEXT_PUBLIC_SSE_BASE;
  if (cfg !== undefined) return cfg;
  const port = process.env.NEXT_PUBLIC_API_PORT || '8000';
  return `${window.location.protocol}//${window.location.hostname}:${port}`;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  formData?: FormData;
  skipAuth?: boolean;
}

async function doFetch<T>(
  path: string,
  options: RequestOptions,
  accessToken: string | null
): Promise<T> {
  const headers: Record<string, string> = {};
  if (!options.formData) {
    headers['Content-Type'] = 'application/json';
  }
  if (!options.skipAuth && accessToken) {
    headers['Authorization'] = `Bearer ${accessToken}`;
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    method: options.method || 'GET',
    headers,
    body: options.formData
      ? options.formData
      : options.body !== undefined
        ? JSON.stringify(options.body)
        : undefined,
  });

  if (!resp.ok) {
    let message = `请求失败 (${resp.status})`;
    try {
      const data = await resp.json();
      if (data?.detail) {
        message = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
      } else if (data?.message) {
        message = data.message;
      }
    } catch {
      // ignore
    }
    throw new ApiError(message, resp.status);
  }

  const text = await resp.text();
  if (!text) return {} as T;
  return JSON.parse(text) as T;
}

async function tryRefreshToken(): Promise<boolean> {
  const { refreshToken, setTokens, clear } = useAuthStore.getState();
  if (!refreshToken) return false;
  try {
    const resp = await fetch(`${BASE_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!resp.ok) {
      clear();
      return false;
    }
    const data = (await resp.json()) as { access_token: string; refresh_token: string };
    setTokens(data.access_token, data.refresh_token);
    return true;
  } catch {
    clear();
    return false;
  }
}

function redirectToLogin() {
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { accessToken } = useAuthStore.getState();
  try {
    return await doFetch<T>(path, options, accessToken);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401 && !options.skipAuth) {
      // token 过期，尝试刷新
      const ok = await tryRefreshToken();
      if (ok) {
        const { accessToken: newToken } = useAuthStore.getState();
        return await doFetch<T>(path, options, newToken);
      }
      redirectToLogin();
      throw err;
    }
    throw err;
  }
}

/**
 * 取一张受鉴权的图片，返回可直接给 `<img src>` 用的 blob URL。
 *
 * 为什么不把照片挂成静态目录、直接写 `<img src="/media/x.jpg">`：
 * 回忆照片的可见性由服务端按「老人本人 / 已绑定家属 且 故事当前可见」判定，
 * 而鉴权走的是 Authorization 头——`<img>` 标签带不上这个头。
 * 所以先 fetch 成 blob，再本地指向它。调用方拿到 URL 后必须
 * `URL.revokeObjectURL()`，否则整页的图片都会一直占着内存。
 */
export async function apiBlobUrl(path: string): Promise<string> {
  const { accessToken } = useAuthStore.getState();
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!resp.ok) {
    throw new ApiError(`照片加载失败 (${resp.status})`, resp.status);
  }
  return URL.createObjectURL(await resp.blob());
}

// ============ 具体接口封装 ============

export interface LoginResp {
  user_id: string;
  username: string;
  role: 'elderly' | 'family';
  access_token: string;
  refresh_token: string;
  elderly_id?: string;
  invite_code?: string;
  name?: string;
  email?: string;
}

export interface EmailCodeResp {
  sent: boolean;
  message: string;
  retry_after: number;
  expires_in?: number;
  debug_code?: string;
}

export const authApi = {
  login: (username: string, password: string) =>
    api<LoginResp>('/auth/login', {
      method: 'POST',
      body: { username, password },
      skipAuth: true,
    }),
  sendEmailCode: (email: string, purpose: 'login' | 'register' | 'bind' = 'login') =>
    api<EmailCodeResp>('/auth/email/code', {
      method: 'POST',
      body: { email, purpose },
      skipAuth: true,
    }),
  emailLogin: (email: string, code: string) =>
    api<LoginResp>('/auth/email/login', {
      method: 'POST',
      body: { email, code },
      skipAuth: true,
    }),
  bindEmail: (email: string, code: string) =>
    api<{ email: string; bound: boolean }>('/auth/email/bind', {
      method: 'POST',
      body: { email, code },
    }),
  register: (data: {
    username: string;
    password: string;
    role: 'elderly' | 'family';
    name?: string;
    invite_code?: string;
    email?: string;
    email_code?: string;
  }) => api<LoginResp>('/auth/register', { method: 'POST', body: data, skipAuth: true }),
  me: () =>
    api<{
      user_id: string;
      username: string;
      role: string;
      elderly_id?: string;
      email?: string;
      name?: string;
    }>('/auth/me'),
  /** 修改老人显示称呼（不修改登录用户名） */
  updateName: (name: string) =>
    api<{ name: string }>('/auth/name', { method: 'PUT', body: { name } }),
  /** 修改登录用户名（需要当前密码；user_id/邀请码不变） */
  updateUsername: (username: string, password: string) =>
    api<{ username: string }>('/auth/username', {
      method: 'PUT',
      body: { username, password },
    }),
};

export interface ChatResp {
  reply: string;
  user_id: number;
  name?: string;
  emotion?: string;
  emotion_intensity?: number;
  intent?: string;
  scene?: string;
  topic?: string;
  need?: string;
  risk_level?: string;
  action?: string;
  action_reason?: string;
  recommendation?: { type?: string; title?: string; content?: string; url?: string } | string;
  degraded?: boolean;
  recalled_memories?: string[];
  knowledge_sources?: Array<{
    document_id: number;
    title: string;
    source?: string;
    score: number;
  }>;
}

/** 按天聚合的情绪趋势（来自 /emotion/trend） */
export interface EmotionTrendDay {
  date: string;
  dominant_emotion: string;
  avg_intensity: number;
  record_count: number;
}

export interface ChatStreamHandlers {
  /** 收到一段文本增量（边生成边回调） */
  onDelta: (text: string) => void;
  /** 生成完成，携带与 /chat 同结构的完整元数据 */
  onDone: (resp: ChatResp) => void;
  /** 失败（含网络中断） */
  onError: (message: string) => void;
}

export const chatApi = {
  send: (message: string) =>
    api<ChatResp>('/chat', { method: 'POST', body: { message } }),

  /**
   * 预生成（"边说边算"）：老人还在说话时，用部分识别结果先让后端把回复算起来。
   * 立即返回，不等待；之后 sendStream 若命中缓存就会跳过分析与生成直接出字。
   */
  speculate: (message: string) =>
    api<{ accepted: boolean }>('/chat/speculate', {
      method: 'POST',
      body: { message },
    }),

  /**
   * 流式聊天：POST /chat/stream（SSE），逐段回调文本增量。
   *
   * 用 fetch + ReadableStream 读 SSE —— EventSource 不支持 POST 与自定义请求头，
   * 拿不到 Authorization。首字延迟因此从"整段生成完"降到"首个 token"。
   */
  sendStream: async (message: string, h: ChatStreamHandlers): Promise<void> => {
    const { accessToken } = useAuthStore.getState();
    // 直连后端：走 Next rewrite 会被缓冲，等于没有流式（见 resolveStreamBase 注释）
    const resp = await fetch(`${resolveStreamBase()}${BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify({ message }),
    });

    if (!resp.ok || !resp.body) {
      let detail = `请求失败 (${resp.status})`;
      try {
        const d = await resp.json();
        if (d?.detail) detail = String(d.detail);
      } catch {
        // 响应不是 JSON，保留默认提示
      }
      h.onError(detail);
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        // SSE 以空行分隔事件；一次 read 可能带来多个事件或半个事件
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = raw.split('\n').find((l) => l.startsWith('data:'));
          if (!line) continue;
          let evt: { type?: string; text?: string; detail?: string } & Partial<ChatResp>;
          try {
            evt = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          if (evt.type === 'delta' && evt.text) h.onDelta(evt.text);
          else if (evt.type === 'done') h.onDone(evt as ChatResp);
          else if (evt.type === 'error') h.onError(evt.detail || '生成失败');
        }
      }
    } catch {
      h.onError('连接中断，请重试');
    }
  },
};

export interface Profile {
  name?: string;
  age?: number;
  gender?: string;
  interests?: string[] | string;
  health?: string;
  [key: string]: unknown;
}

export const profileApi = {
  get: () => api<Profile>('/profile'),
  update: (data: Partial<Profile>) =>
    api<Profile>('/profile', { method: 'PUT', body: data }),
};

export interface EmotionRecord {
  emotion: string;
  intensity: number;
  created_at: string;
}

/** 摄像头表情识别结果（DeepFace，POST /emotion/face） */
export interface FaceEmotionResult {
  face_found: boolean;
  emotion: string;
  emotion_label: string;
  score: number;
  scores: Record<string, number>;
  region?: { x: number; y: number; w: number; h: number } | null;
  detector?: string;                // 命中的检测器：opencv / retinaface
  face_confidence?: number | null;  // 人脸检测置信度 0~1
  dog_reacted: boolean;
  dog_reached: boolean;
  speech: string;
  created_at: string;
}

export const emotionApi = {
  history: (limit = 20) =>
    api<{ records: EmotionRecord[] }>(`/emotion/history?limit=${limit}`),
  trend: (days = 7) =>
    api<EmotionTrendDay[]>(`/emotion/trend?days=${days}`),
  /** 摄像头抓帧 → 后端 DeepFace 表情识别（react=true 时持续负面会触发狗安慰） */
  face: (file: Blob, react = false) => {
    const fd = new FormData();
    fd.append('file', file, 'face.jpg');
    fd.append('react', react ? 'true' : 'false');
    return api<FaceEmotionResult>('/emotion/face', {
      method: 'POST',
      formData: fd,
    });
  },
};

export interface MemoryItem {
  id: number;
  memory_type: string;
  content: string;
  importance: number;
  created_at: string;
}

export const memoryApi = {
  list: () => api<MemoryItem[]>('/profile/memories').then((arr) => ({ memories: arr })),
  remove: (id: number) => api(`/profile/memories/${id}`, { method: 'DELETE' }),
  state: () => api<{ state: unknown; recent: unknown }>('/emotion/memory-state'),
};

export interface MusicItem {
  title: string;
  artist: string;
  tags?: string[];
  score?: number;
  reason?: string;
}

export interface StoryItem {
  title: string;
  tags?: string[];
  mood?: string[];
  summary?: string;
  length?: string;
  score?: number;
}

export interface RecommendResp<T> {
  user_id: string | number;
  emotion?: string;
  scene?: string;
  items: T[];
}

export const recommendApi = {
  music: (limit = 3) =>
    api<RecommendResp<MusicItem>>(`/recommend/music?limit=${limit}`, { method: 'POST' }),
  story: (limit = 3) =>
    api<RecommendResp<StoryItem>>(`/recommend/story?limit=${limit}`, { method: 'POST' }),
};

export const speechApi = {
  tts: (text: string, voice?: string) =>
    api<{ audio_url: string }>('/speech/tts', {
      method: 'POST',
      body: { text, voice },
    }),
  asrSubmit: (file: Blob) => {
    const fd = new FormData();
    fd.append('file', file, 'recording.webm');
    return api<{ task_id: string; status: string }>('/speech/asr/submit', {
      method: 'POST',
      formData: fd,
    });
  },
  asrResult: (taskId: string) =>
    api<{ task_id: string; status: string; text?: string; error?: string }>(
      `/speech/asr/${taskId}`
    ),
};

/** 视觉：拍照 → 小智视觉服务描述（桥接 xiaozhi-esp32-server） */
export const visionApi = {
  describe: (file: Blob, question?: string) => {
    const fd = new FormData();
    fd.append('question', question || '');
    fd.append('file', file, 'photo.jpg');
    return api<{ description: string; question: string }>('/vision/describe', {
      method: 'POST',
      formData: fd,
    });
  },
  /** 拍照 → 识别场景 → 机器狗做出相应动作 */
  react: (file: Blob, question?: string) => {
    const fd = new FormData();
    fd.append('question', question || '');
    fd.append('file', file, 'photo.jpg');
    return api<{
      description: string;
      question: string;
      actions: string[];
      speech: string;
      dog_reached: boolean;
    }>('/vision/react', { method: 'POST', formData: fd });
  },
  status: () =>
    api<{
      vision_online: boolean;
      vision_detail: string;
      dog_online: boolean;
      dog_detail: string;
    }>('/vision/status'),
};

/** 机器狗：前端视觉引擎实时驱动 */
export const dogApi = {
  action: (actionKey: string, duration?: number) =>
    api<{
      success: boolean;
      action_key: string;
      action_name: string;
      dog_reached: boolean;
      message: string;
    }>('/dog/action', {
      method: 'POST',
      body: { action_key: actionKey, duration },
    }),
  listActions: () =>
    api<Array<{ key: string; name: string; hint: string }>>('/dog/actions'),
  /** 家属让小狗给老人传话（仅传话，不指挥动作） */
  relay: (elderlyUserId: string, relation: string, content: string) =>
    api<{ status: string; text: string; message: string }>('/dog/relay', {
      method: 'POST',
      body: { elderly_user_id: elderlyUserId, relation, content },
    }),
  /** 老人端：拉取未送达的小狗传话（上线补播），取出即标记已读 */
  pendingRelays: () =>
    api<{ relays: Array<{ id: number; text: string; dog_spoke?: boolean; created_at?: string | null }> }>(
      '/dog/relays'
    ),
};

export interface ElderlyItem {
  elderly_id: string;
  username: string;
  name?: string;
}

export interface FamilyAlert {
  id: number;
  elderly_user_id: string;
  alert_type: string;
  severity: string;
  title: string;
  detail: string;
  is_acknowledged: boolean;
  acknowledged_by?: string | null;
  acknowledged_at?: string | null;
  created_at: string;
}

export interface FamilyMessageItem {
  id: number;
  family_user_id: string;
  elderly_user_id: string;
  content: string;
  category: string;
  sender_role: 'family' | 'elderly';
  is_read: boolean;
  reaction?: string | null;
  created_at: string;
  read_at?: string | null;
}

export interface FamilyPerson {
  family_user_id: string;
  relationship_name: string;
}

/** 每日陪伴日报 content（JSON）的结构 */
export interface DigestStats {
  rounds: number;
  main_emotion: string;
  main_emotion_label: string;
  topics: { topic: string; count: number }[];
  time_range: string;
}
/** 日报里的回忆录增量（只含老人愿意分享的条目） */
export interface DigestMemoir {
  today: number;
  week: number;
  total: number;
}
export interface DigestPayload {
  date?: string;
  summary?: string;
  stats?: DigestStats;
  memoir?: DigestMemoir;
}

/** 对话节律：7×24 计数矩阵（只含时间，不含对话内容） */
export interface ChatRhythm {
  user_id: string;
  days: number;
  matrix: number[][];
  weekday_labels: string[];
  total_rounds: number;
  active_days: number;
  peak: { weekday: number; hour: number; count: number } | null;
  night_rounds: number;
  night_ratio: number;
  generated_at: string;
}

/** 关怀指数单个因子 */
export interface CareFactor {
  key: string;
  label: string;
  score: number;
  max: number;
  detail: string;
}

/** 关怀指数（0-100 + 因子明细） */
export interface CareIndex {
  user_id: string;
  score: number;
  level: 'good' | 'watch' | 'risk';
  advice: string;
  factors: CareFactor[];
  generated_at: string;
}

/** 记忆图谱：人物 × 话题共现（只含词与计数，不含记忆原文） */
export interface MemoryGraph {
  user_id: string;
  elderly_name: string;
  memory_count: number;
  persons: { label: string; count: number }[];
  topics: { label: string; count: number }[];
  edges: { person: string; topic: string; count: number }[];
}

/** 回忆录流水线的一个阶段 */
export interface MemoirPipelineStage {
  key: string;
  label: string;
  detail: string;
  items: { label: string; count: number }[];
}
/** 回忆录流水线（只统计家属可见条目） */
export interface MemoirPipelineData {
  user_id: string;
  stages: MemoirPipelineStage[];
  era_tags: { label: string; count: number }[];
  privacy_note: string;
}

/** 陪伴需求信号（家属端：老人在要什么） */
export interface CareSignal {
  key: string;
  label: string;
  icon: string;
  count: number;
  prev: number;
  delta: number;
  level: 'high' | 'medium' | 'low' | 'none';
  hint: string;
}
export interface CareSignals {
  user_id: string;
  window_days: number;
  signals: CareSignal[];
  top_topics: { label: string; count: number }[];
  scene_summary: { alone: number; silence_checkin: number; total: number };
  silence_note: string;
  generated_at: string;
}

/** 人生河（老人端）：AI 成长 + 回忆时光河 */
export interface GrowthMonth {
  month: string;
  count: number;
  by_type: Record<string, number>;
}
export interface RiverStory {
  id: number;
  title: string;
  summary: string;
  time_value: string;
  era_label: string;
  emotion_tone: string;
  tone_color: 'amber' | 'blue' | 'gray';
  completeness: number;
  visibility: string;
}
export interface RiverStage {
  label: string;
  stories: RiverStory[];
}
export interface Journey {
  user_id: string;
  elderly_name: string;
  memory_count: number;
  days_together: number;
  first_memory_at: string | null;
  this_month_memories: number;
  growth_months: GrowthMonth[];
  river_stages: RiverStage[];
  river_total: number;
  generated_at: string;
}

/** 老人端「AI 眼中的你」画像卡 */
export interface Portrait {
  user_id: string;
  elderly_name: string;
  memory_count: number;
  days_together: number;
  interests: string[];
  favorite_music: string[];
  taboos: string[];
  top_persons: { label: string; count: number }[];
  top_topics: { label: string; count: number }[];
  habit_hour: number | null;
  habit_text: string;
  generated_at: string;
}

/** 老人端「人生之书」 */
export interface BookStory {
  id: number;
  title: string;
  summary: string;
  time_value: string;
  emotion_tone: string;
  tone_color: 'amber' | 'blue' | 'gray';
  completeness: number;
}
export interface BookChapter {
  stage: string;
  intro: string;
  stories: BookStory[];
}
export interface LifeBook {
  user_id: string;
  author_name: string;
  age: number | null;
  title: string;
  chapter_count: number;
  story_count: number;
  chapters: BookChapter[];
  generated_at: string;
}

/** 机器狗传话记录（家属端） */
export interface DogLogRecord {
  id: number;
  content: string;
  is_read: boolean;
  reaction?: string | null;
  created_at: string;
  read_at: string | null;
}
export interface DogLog {
  user_id: string;
  total_runs: number;
  read_count: number;
  unread_count: number;
  read_rate: number;
  last_run_at: string | null;
  top_relations: { label: string; count: number }[];
  records: DogLogRecord[];
  generated_at: string;
}

/** 老人端「人生河」（仅本人可见） */
export const journeyApi = {
  me: () => api<Journey>('/journey/me'),
  portrait: () => api<Portrait>('/journey/portrait'),
};

/** 老人端「人生之书」（仅本人可见） */
export const bookApi = {
  me: () => api<LifeBook>('/book/me'),
};

export const familyApi = {
  list: () => api<{ elderly: ElderlyItem[] } | ElderlyItem[]>('/family/elderly'),
  bind: (elderlyUsername: string, inviteCode: string) =>
    api('/family/bind', {
      method: 'POST',
      body: { elderly_username: elderlyUsername, invite_code: inviteCode },
    }),
  emotion: (elderlyId: string, limit = 20) =>
    api<{ records: EmotionRecord[] }>(
      `/family/elderly/${elderlyId}/emotion?limit=${limit}`
    ),
  emotionTrend: (elderlyId: string, days = 7) =>
    api<EmotionTrendDay[]>(
      `/emotion/${elderlyId}/trend?days=${days}`
    ),
  /** 对话节律热力图数据（7×24 矩阵，只含计数） */
  chatRhythm: (elderlyId: string, days = 28) =>
    api<ChatRhythm>(`/family/elderly/${elderlyId}/rhythm?days=${days}`),
  /** 关怀指数（0-100 + 四个可解释因子） */
  careIndex: (elderlyId: string) =>
    api<CareIndex>(`/family/elderly/${elderlyId}/care-index`),
  /** 记忆图谱（人物 × 话题共现，只含词与计数） */
  memoryGraph: (elderlyId: string) =>
    api<MemoryGraph>(`/family/elderly/${elderlyId}/memory-graph`),
  /** 回忆录流水线（线索 → 留档 → 隐私分级 → 家属可见） */
  memoirPipeline: (elderlyId: string) =>
    api<MemoirPipelineData>(`/family/elderly/${elderlyId}/memoir-pipeline`),
  /** 陪伴需求信号（老人在要什么：孤独/思念/健康/回忆/内容） */
  careSignals: (elderlyId: string) =>
    api<CareSignals>(`/family/elderly/${elderlyId}/care-signals`),
  /** 机器狗传话记录（跑了几趟、谁最常带话、老人看了没有） */
  dogLog: (elderlyId: string) =>
    api<DogLog>(`/family/elderly/${elderlyId}/dog-log`),
  memories: (elderlyId: string) =>
    api<{ memories: MemoryItem[] }>(
      `/family/elderly/${elderlyId}/memories`
    ),
  alerts: () => api<FamilyAlert[]>('/family/alerts'),
  ackAlert: (alertId: number) =>
    api<{ status: string; alert_id: number }>(
      `/family/alerts/${alertId}/ack`,
      { method: 'POST' }
    ),
  /** 家属给老人留言 */
  sendMessage: (elderlyId: string, content: string, category = 'greeting') =>
    api<{ id: number; status: string }>(`/family/elderly/${elderlyId}/messages`, {
      method: 'POST',
      body: { content, category },
    }),
  /** 家属视角：我发给老人的（sent）+ 老人发给我的（inbox） */
  sentMessages: (elderlyId: string) =>
    api<{ sent: FamilyMessageItem[]; inbox: FamilyMessageItem[] }>(
      `/family/elderly/${elderlyId}/messages`
    ),

  // ----- 回忆录（M6）：只读时间轴与短片 + 只能补/撤照片 -----

  /** 老人**已留档且家属可见**的回忆录时间轴（创伤 private 条目根本不会出现） */
  memoir: (elderlyId: string) =>
    api<MemoirTimeline>(`/family/elderly/${elderlyId}/memoir`),
  /** 老人已排好的短片提示词包（镜头已按当下可见性再过滤过） */
  memoirCompilations: (elderlyId: string) =>
    api<CompilationItem[]>(`/family/elderly/${elderlyId}/memoir/compilations`),
  /**
   * 给老人一条看得见的往事补一张照片。
   * 注意这里**没有** confirm / discard / createCompilation——那三样是老人专属。
   */
  uploadStoryPhoto: (elderlyId: string, storyId: number, file: File, caption = '') => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('caption', caption);
    return api<StoryMediaItem>(
      `/family/elderly/${elderlyId}/memoir/stories/${storyId}/media`,
      { method: 'POST', formData: fd }
    );
  },
  /** 撤回自己上传的照片（删是让信息变少，所以老人改成 private 后仍然允许） */
  deleteStoryMedia: (elderlyId: string, mediaId: number) =>
    api<{ deleted: boolean; id: number }>(
      `/family/elderly/${elderlyId}/memoir/media/${mediaId}`,
      { method: 'DELETE' }
    ),
  /**
   * 立即获取今日陪伴日报（不必等每天 20:30 的定时推送）。
   * 今天已生成过则直接返回已有内容；没有任何动静时 digest 为 null。
   */
  refreshDigestToday: (elderlyId: string) =>
    api<{
      status: string;
      generated: boolean;
      digest: DigestPayload | null;
      reason?: string;
      date?: string;
    }>(`/family/elderly/${elderlyId}/digest/today`, { method: 'POST' }),
  /** 家属端只读健康摘要：用药 / 近期待复诊 / 最近记录 / 依从率 */
  healthCare: (elderlyId: string) =>
    api<FamilyHealthSummary>(`/family/elderly/${elderlyId}/health-care`),
  /** 家属端可见的时光信笺（仅"已到点 + 明确设为家人可见"） */
  letters: (elderlyId: string) =>
    api<{ letters: FamilyLetter[]; scheduled_count: number; generated_at: string }>(
      `/family/elderly/${elderlyId}/letters`
    ),
};

/** 老人端：与家人双向留言 */
export const familyMessageApi = {
  received: () =>
    api<{ unread: number; inbox: FamilyMessageItem[]; sent: FamilyMessageItem[] }>(
      '/family/messages'
    ),
  myFamilies: () => api<{ families: FamilyPerson[] }>('/family/my-families'),
  send: (content: string, familyUserId: string, category = 'greeting') =>
    api<{ id: number; status: string }>('/family/messages', {
      method: 'POST',
      body: { content, family_user_id: familyUserId, category },
    }),
  markRead: (id: number, reaction?: string) =>
    api<{ status: string }>(
      `/family/messages/${id}/read${reaction ? `?reaction=${encodeURIComponent(reaction)}` : ''}`,
      { method: 'POST' }
    ),
};

// ============ RAG 知识库 ============
export interface KnowledgeDocument {
  id: number;
  title: string;
  source: string;
  scope: 'global' | 'elderly';
  elderly_user_id?: string | null;
  chunk_count: number;
  created_by?: string | null;
  created_at: string;
  updated_at?: string;
  embedded?: boolean;
}

export interface KnowledgeHit {
  chunk_id: number;
  document_id: number;
  title: string;
  source: string;
  scope: 'global' | 'elderly';
  content: string;
  score: number;
}

export const knowledgeApi = {
  list: () => api<{ documents: KnowledgeDocument[] }>('/knowledge/documents'),
  create: (data: {
    title: string;
    content: string;
    source?: string;
    scope: 'global' | 'elderly';
    elderly_user_id?: string;
  }) => api<KnowledgeDocument>('/knowledge/documents', { method: 'POST', body: data }),
  remove: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/knowledge/documents/${id}`, { method: 'DELETE' }),
  search: (query: string, elderlyUserId?: string, topK = 5) =>
    api<{ query: string; results: KnowledgeHit[] }>('/knowledge/search', {
      method: 'POST',
      body: { query, elderly_user_id: elderlyUserId || undefined, top_k: topK },
    }),
};

// ============ 回忆录（生平故事）============

/** 一条回忆录条目（老人端视图）。
 *  注意：不要叫 StoryItem——api.ts 里已有推荐用的 StoryItem，会撞名。 */
export interface MemoirStory {
  id: number;
  title: string;
  summary: string;
  time_type: string;
  time_value: string;
  time_confidence: number;
  time_inferred: boolean;
  era_tags: string[];
  place: string;
  people: string[];
  emotion_tone: string;
  completeness: number;
  status: string; // draft / pending_confirm / archived / discarded
  created_at: string;
  /** 后端拼好的留档确认语，可直接交给 TTS 念 */
  speak_text: string;
  /** 挂在这条回忆上的照片（老人与家属都看得到） */
  media: StoryMediaItem[];
}

/** 回忆里的一张照片。
 *  `url` 是鉴权读接口路径，不能直接塞进 `<img src>`——用 apiBlobUrl() 取 blob。 */
export interface StoryMediaItem {
  id: number;
  type: string;
  caption: string;
  url: string;
  /** owner = 老人本人上传；family = 家属上传 */
  uploaded_by_role: 'owner' | 'family' | 'unknown' | string;
  created_at: string;
}

export const memoirApi = {
  /** 老人端：待确认的回忆条目 */
  pendingStories: () => api<MemoirStory[]>('/stories/pending'),
  /** 老人点「留下这段」（via=voice 表示语音确认，契约1） */
  confirmStory: (id: number, via: 'button' | 'voice' = 'button') =>
    api<MemoirStory>(`/stories/${id}/confirm`, { method: 'POST', body: { via } }),
  /** 老人点「先不用」 */
  discardStory: (id: number, via: 'button' | 'voice' = 'button') =>
    api<MemoirStory>(`/stories/${id}/discard`, { method: 'POST', body: { via } }),
  /** 把弃用的条目放回待确认 */
  restoreStory: (id: number) =>
    api<MemoirStory>(`/stories/${id}/restore`, { method: 'POST' }),
  /** 老人端回忆录时间轴（三组互斥：时代轴 / 绝对时间轴 / 未定位） */
  timeline: (status: 'archived' | 'all' = 'archived') =>
    api<MemoirTimeline>(`/memoir/timeline?status=${status}`),

  /** 已生成的短片故事板列表 */
  compilations: () => api<CompilationItem[]>('/memoir/compilations'),
  /** 把已留档的故事排成一条短片故事板（同步产包，2~4 秒） */
  createCompilation: (body: { title?: string; story_ids?: number[]; total_seconds?: number }) =>
    api<CompilationItem>('/memoir/compilations', { method: 'POST', body }),
  compilation: (id: number) => api<CompilationItem>(`/memoir/compilations/${id}`),
  deleteCompilation: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/memoir/compilations/${id}`, { method: 'DELETE' }),

  /** 老人给自己的回忆补一张照片（不改原文、不改可见性） */
  uploadStoryPhoto: (storyId: number, file: File, caption = '') => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('caption', caption);
    return api<StoryMediaItem>(`/memoir/stories/${storyId}/media`, {
      method: 'POST',
      formData: fd,
    });
  },
  /** 老人删掉自家回忆上的任意一张照片 */
  deleteMedia: (mediaId: number) =>
    api<{ deleted: boolean; id: number }>(`/memoir/media/${mediaId}`, { method: 'DELETE' }),
};

/** 时间轴上的一条卡片。
 *  `display_time` 是后端拼好的展示串（推断值带「约」字前缀），
 *  `time_value` 才是原始记录——契约5：不纠正、只标注。 */
export interface TimelineStory extends MemoirStory {
  display_time: string;
  /** 推断依据的画像条目（为空表示时间来自原始记录） */
  inferred_from: string;
  /** 所属时代（多时代标签时取最早的那一段） */
  era: string;
}

export interface EraAxisGroup {
  era: string;
  start_year: number | null;
  end_year: number | null;
  color: string;
  count: number;
  stories: TimelineStory[];
}

export interface TimelineStats {
  total: number;
  era_segments: number;
  in_era: number;
  in_absolute: number;
  unlocated: number;
  /** 由画像保守推断出时间的条数（全部 ≤ 0.5 置信度） */
  inferred: number;
}

export interface MemoirTimeline {
  user_id: string;
  era_axis: EraAxisGroup[];
  absolute_axis: TimelineStory[];
  unlocated: TimelineStory[];
  axis_span: { min_year: number | null; max_year: number | null };
  stats: TimelineStats;
}

/** 故事板的一段镜头。契约6：这里只有提示词，没有任何画面文件。 */
export interface StoryboardScene {
  index: number;
  story_id: number;
  era: string;
  title: string;
  display_time: string;
  place: string;
  emotion_tone: string;
  duration_seconds: number;
  narration: string;
  /** original = 直接用了老人原话（契约4）；model = 模型顺过语气 */
  narration_source: 'original' | 'model' | string;
  visual_prompt: string;
  /** 出处，永远是老人原话 */
  source_evidence: string;
}

export interface PromptPackage {
  title: string;
  perspective: string;
  /** 实际总时长（秒）。段数太少时会短于 requested_seconds，如实显示 */
  total_seconds: number;
  requested_seconds: number;
  disclaimer: string;
  scenes: StoryboardScene[];
  /** 恒为 null —— 本系统不接任何生成服务（契约6） */
  render_engine: null;
  /** LLM 是否可用；false 表示走了线性降级 */
  llm_used: boolean;
}

export interface CompilationItem {
  id: number;
  title: string;
  perspective: string;
  /** 只会是 queued / prompt_ready —— 不存在"渲染完成"这种状态（契约6） */
  status: string;
  story_ids: number[];
  prompt_package: PromptPackage | null;
  created_at: string;
  /** 恒为 null（契约6） */
  video_url: string | null;
  /** 恒为 false（契约6） */
  rendered: boolean;
}

// ============ 健康关怀 ============

export interface DueReminder {
  key: string;
  kind: 'medication' | 'appointment';
  ref_id: number;
  title: string;
  detail: string;
  scheduled_for: string;
  minutes_until: number;
  /** 已过分钟数；负数表示还没到点 */
  overdue_minutes?: number;
  /** '' = 还没发过；sent = 发了没确认；acknowledged 不会出现在待办里 */
  log_status: string;
  log_id: number | null;
  message: string;
}

export interface UpcomingReminder {
  key: string;
  kind: 'medication' | 'appointment';
  ref_id: number;
  title: string;
  detail: string;
  scheduled_for: string;
  minutes_until: number;
}

export interface HealthMedication {
  id: number;
  name: string;
  dosage: string;
  times: string[];
  frequency: 'daily' | 'weekly' | 'as_needed' | string;
  weekdays: number[];
  start_date: string;
  end_date: string;
  note: string;
  active: boolean;
  created_at: string;
}

export interface HealthAppointment {
  id: number;
  title: string;
  hospital: string;
  department: string;
  doctor: string;
  appointment_at: string;
  location: string;
  note: string;
  remind_before_minutes: number;
  status: 'scheduled' | 'done' | 'cancelled' | string;
  created_at: string;
}

/** 血压分级：只表示"在参考区间的哪一段"，不是诊断 */
export interface HealthLevel {
  key: string;
  label: string;
  color: string;
  advice: string;
}

export interface HealthRecordItem {
  id: number;
  record_type: string;
  record_label: string;
  systolic: number | null;
  diastolic: number | null;
  pulse: number | null;
  value: number | null;
  unit: string;
  measured_at: string;
  note: string;
  created_at: string;
  level: HealthLevel;
}

export interface HealthOverview {
  today: string;
  now: string;
  due: DueReminder[];
  upcoming: UpcomingReminder[];
  medications: HealthMedication[];
  appointments: HealthAppointment[];
  records: HealthRecordItem[];
  latest_blood_pressure: HealthRecordItem | null;
}

export interface FamilyHealthSummary {
  user_id: string;
  medications: HealthMedication[];
  appointments: HealthAppointment[];
  records: HealthRecordItem[];
  latest_blood_pressure: HealthRecordItem | null;
  adherence: {
    days: number;
    expected: number;
    acknowledged: number;
    missed: number;
    rate: number | null;
  };
  due: DueReminder[];
  generated_at: string;
}

export interface MedicationPayload {
  name: string;
  dosage?: string;
  times: string[];
  frequency?: 'daily' | 'weekly' | 'as_needed';
  weekdays?: number[];
  start_date?: string;
  end_date?: string;
  note?: string;
  active?: boolean;
}

export interface AppointmentPayload {
  title: string;
  hospital?: string;
  department?: string;
  doctor?: string;
  appointment_at: string;
  location?: string;
  note?: string;
  remind_before_minutes?: number;
  status?: 'scheduled' | 'done' | 'cancelled';
}

export interface HealthRecordPayload {
  record_type: string;
  systolic?: number;
  diastolic?: number;
  pulse?: number;
  value?: number;
  unit?: string;
  measured_at?: string;
  note?: string;
}

export const healthCareApi = {
  overview: () => api<HealthOverview>('/health-care/overview'),
  /** 只拉未确认的提醒（全局弹窗轮询用） */
  due: () =>
    api<{ count: number; items: DueReminder[]; generated_at: string }>('/health-care/due'),
  createMedication: (data: MedicationPayload) =>
    api<HealthMedication>('/health-care/medications', { method: 'POST', body: data }),
  updateMedication: (id: number, data: MedicationPayload) =>
    api<HealthMedication>(`/health-care/medications/${id}`, { method: 'PUT', body: data }),
  deleteMedication: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/health-care/medications/${id}`, { method: 'DELETE' }),
  createAppointment: (data: AppointmentPayload) =>
    api<HealthAppointment>('/health-care/appointments', { method: 'POST', body: data }),
  updateAppointment: (id: number, data: AppointmentPayload) =>
    api<HealthAppointment>(`/health-care/appointments/${id}`, { method: 'PUT', body: data }),
  doneAppointment: (id: number) =>
    api<{ status: string; id: number }>(`/health-care/appointments/${id}/done`, { method: 'POST' }),
  deleteAppointment: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/health-care/appointments/${id}`, { method: 'DELETE' }),
  createRecord: (data: HealthRecordPayload) =>
    api<HealthRecordItem>('/health-care/records', { method: 'POST', body: data }),
  listRecords: (recordType?: string, limit = 30) =>
    api<{ records: HealthRecordItem[] }>(
      `/health-care/records?limit=${limit}${recordType ? `&record_type=${recordType}` : ''}`
    ),
  deleteRecord: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/health-care/records/${id}`, { method: 'DELETE' }),
  ack: (data: { kind: string; ref_id: number; scheduled_for: string }) =>
    api<{ status: string; id: number }>('/health-care/reminders/ack', {
      method: 'POST',
      body: data,
    }),
};

// ============ 时光信笺 ============

export interface TimeLetter {
  id: number;
  title: string;
  content: string;
  recipient_type: 'self' | 'family';
  recipient_name: string;
  deliver_at: string;
  visibility: 'private' | 'family';
  status: 'scheduled' | 'delivered' | 'read';
  days_until: number;
  seconds_until: number;
  opened_at: string | null;
  created_at: string;
  can_edit: boolean;
  can_delete: boolean;
}

export interface FamilyLetter {
  id: number;
  title: string;
  content: string;
  recipient_type: string;
  recipient_name: string;
  deliver_at: string;
  created_at: string;
}

export interface LetterPayload {
  title?: string;
  content: string;
  recipient_type: 'self' | 'family';
  recipient_name?: string;
  deliver_at: string;
  visibility: 'private' | 'family';
}

export const letterApi = {
  list: () =>
    api<{
      letters: TimeLetter[];
      scheduled: TimeLetter[];
      delivered: TimeLetter[];
      read: TimeLetter[];
      unread_count: number;
    }>('/letters'),
  due: () => api<{ count: number; letters: TimeLetter[] }>('/letters/due'),
  create: (data: LetterPayload) => api<TimeLetter>('/letters', { method: 'POST', body: data }),
  update: (id: number, data: Partial<LetterPayload>) =>
    api<TimeLetter>(`/letters/${id}`, { method: 'PUT', body: data }),
  open: (id: number) => api<TimeLetter>(`/letters/${id}/open`, { method: 'POST' }),
  remove: (id: number) =>
    api<{ deleted: boolean; id: number }>(`/letters/${id}`, { method: 'DELETE' }),
};

// ============ 方言模式 ============

export interface DialectOption {
  name: string;
  enabled: boolean;
  style: string;
}

export interface DialectState {
  enabled: boolean;
  dialect: string;
  active_dialect: string;
  options: DialectOption[];
}

export const settingsApi = {
  dialect: () => api<DialectState>('/settings/dialect'),
  setDialect: (enabled: boolean, dialect: string) =>
    api<DialectState>('/settings/dialect', {
      method: 'PUT',
      body: { enabled, dialect },
    }),
};

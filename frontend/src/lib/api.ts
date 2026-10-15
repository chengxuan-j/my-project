'use client';

import { useAuthStore } from '@/stores/auth';

const BASE_URL = '/api/v1';

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
  me: () => api<{ user_id: string; username: string; role: string; elderly_id?: string; email?: string }>('/auth/me'),
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

export const chatApi = {
  send: (message: string) =>
    api<ChatResp>('/chat', { method: 'POST', body: { message } }),
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

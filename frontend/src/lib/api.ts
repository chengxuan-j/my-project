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

export const emotionApi = {
  history: (limit = 20) =>
    api<{ records: EmotionRecord[] }>(`/emotion/history?limit=${limit}`),
  trend: (days = 7) =>
    api<EmotionTrendDay[]>(`/emotion/trend?days=${days}`),
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

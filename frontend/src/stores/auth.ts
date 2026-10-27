'use client';

import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export interface UserInfo {
  user_id: string;
  username: string;
  role: 'elderly' | 'family';
  elderly_id?: string;
  name?: string;
}

/** 一个已登录账号的会话 */
export interface Session {
  key: string; // 唯一键，取 user_id
  user: UserInfo;
  accessToken: string;
  refreshToken: string;
}

interface AuthState {
  // 当前「激活」账号的会话（保持与既有页面用法兼容）
  user: UserInfo | null;
  accessToken: string | null;
  refreshToken: string | null;
  // 多账号并存：同一浏览器可同时保留老人 + 家属登录态
  sessions: Session[];
  activeId: string | null;

  /** 登录成功后写入/更新一个账号会话，并设为激活 */
  setAuth: (user: UserInfo, accessToken: string, refreshToken: string) => void;
  /** 刷新 token：只更新当前激活账号的 token */
  setTokens: (accessToken: string, refreshToken: string) => void;
  /** 改称呼后同步本地会话，导航栏/聊天头部立即生效 */
  updateUserName: (name: string) => void;
  /** 改登录名后同步本地会话（下次登录用新名字） */
  updateLoginName: (username: string) => void;
  /** 切换激活账号 */
  switchAccount: (key: string) => void;
  /** 退出指定账号（若退出的是激活账号，则自动切到剩余的第一个） */
  removeAccount: (key: string) => void;
  /** 退出当前激活账号（兼容旧调用） */
  clear: () => void;
}

function activeFrom(sessions: Session[], activeId: string | null) {
  const s = sessions.find((x) => x.key === activeId) || null;
  return {
    user: s ? s.user : null,
    accessToken: s ? s.accessToken : null,
    refreshToken: s ? s.refreshToken : null,
  };
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      sessions: [],
      activeId: null,

      setAuth: (user, accessToken, refreshToken) => {
        const key = user.user_id;
        const others = get().sessions.filter((s) => s.key !== key);
        const sessions = [...others, { key, user, accessToken, refreshToken }];
        set({ sessions, activeId: key, ...activeFrom(sessions, key) });
      },

      setTokens: (accessToken, refreshToken) => {
        const { sessions, activeId } = get();
        if (!activeId) {
          set({ accessToken, refreshToken });
          return;
        }
        const next = sessions.map((s) =>
          s.key === activeId ? { ...s, accessToken, refreshToken } : s
        );
        set({ sessions: next, ...activeFrom(next, activeId) });
      },

      updateUserName: (name) => {
        const { sessions, activeId, user } = get();
        if (!activeId) {
          if (user) set({ user: { ...user, name } });
          return;
        }
        const next = sessions.map((s) =>
          s.key === activeId ? { ...s, user: { ...s.user, name } } : s
        );
        set({ sessions: next, ...activeFrom(next, activeId) });
      },

      updateLoginName: (username) => {
        const { sessions, activeId, user } = get();
        if (!activeId) {
          if (user) set({ user: { ...user, username } });
          return;
        }
        const next = sessions.map((s) =>
          s.key === activeId ? { ...s, user: { ...s.user, username } } : s
        );
        set({ sessions: next, ...activeFrom(next, activeId) });
      },

      switchAccount: (key) => {
        const { sessions } = get();
        set({ activeId: key, ...activeFrom(sessions, key) });
      },

      removeAccount: (key) => {
        const sessions = get().sessions.filter((s) => s.key !== key);
        const activeId =
          get().activeId === key ? (sessions[0]?.key ?? null) : get().activeId;
        set({ sessions, activeId, ...activeFrom(sessions, activeId) });
      },

      clear: () => {
        const id = get().activeId;
        if (id) get().removeAccount(id);
      },
    }),
    {
      name: 'auth-storage',
      version: 1,
      // 从旧的单账号结构迁移到多账号 sessions
      migrate: (persisted, _version) => {
        const p = (persisted ?? {}) as Partial<AuthState> & {
          user?: UserInfo | null;
          accessToken?: string | null;
          refreshToken?: string | null;
        };
        if (!Array.isArray(p.sessions)) {
          if (p.user && p.accessToken) {
            const s: Session = {
              key: p.user.user_id,
              user: p.user,
              accessToken: p.accessToken,
              refreshToken: p.refreshToken ?? '',
            };
            return { ...p, sessions: [s], activeId: s.key };
          }
          return { ...p, sessions: [], activeId: null };
        }
        return p;
      },
    }
  )
);

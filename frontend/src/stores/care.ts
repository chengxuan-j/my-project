'use client';

import { create } from 'zustand';
import type { DueReminder } from '@/lib/api';

/**
 * 关怀提醒的全局状态：
 * - dueCount 给导航栏红点用；
 * - preview 给「试一下提醒效果」用，只影响弹窗，不写任何数据。
 * 不持久化——它随时会变，存下来反而会显示过期的红点。
 */
interface CareState {
  dueCount: number;
  preview: DueReminder[] | null;
  setDueCount: (n: number) => void;
  showPreview: (items: DueReminder[]) => void;
  clearPreview: () => void;
}

export const useCareStore = create<CareState>((set) => ({
  dueCount: 0,
  preview: null,
  setDueCount: (dueCount) => set({ dueCount }),
  showPreview: (preview) => set({ preview }),
  clearPreview: () => set({ preview: null }),
}));

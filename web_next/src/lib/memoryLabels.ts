/** 长期记忆类型的中文标签、图标与展示顺序（与后端 memory_extractor.ALLOWED_TYPES 一致）。 */
export const MEMORY_TYPE_ORDER = [
  'family',
  'life_experience',
  'interest',
  'preference',
  'health',
  'habit',
  'social',
  'place',
  'general',
] as const;

export const MEMORY_TYPE_LABEL: Record<string, string> = {
  family: '家人',
  life_experience: '人生经历',
  interest: '兴趣爱好',
  preference: '喜好偏好',
  health: '身体健康',
  habit: '生活习惯',
  social: '老友社交',
  place: '常去的地方',
  general: '其他',
};

export const MEMORY_TYPE_ICON: Record<string, string> = {
  family: '👨‍👩‍👧',
  life_experience: '📖',
  interest: '🎯',
  preference: '❤️',
  health: '💊',
  habit: '🔁',
  social: '🤝',
  place: '📍',
  general: '💭',
};

export function memoryTypeLabel(type?: string): string {
  return (type && MEMORY_TYPE_LABEL[type]) || type || '其他';
}

export function memoryTypeIcon(type?: string): string {
  return (type && MEMORY_TYPE_ICON[type]) || '💭';
}

/** importance 规范为 1~5 星：兼容后端的 0~1 小数与可能的 1~5 整数。 */
export function importanceStars(importance?: number): number {
  if (typeof importance !== 'number' || Number.isNaN(importance)) return 3;
  const normalized = importance > 1 ? importance / 5 : importance;
  return Math.max(1, Math.min(5, Math.round(normalized * 5)));
}

export function importanceText(importance?: number): string {
  const stars = importanceStars(importance);
  return stars >= 5 ? '很重要' : stars >= 4 ? '比较重要' : stars >= 3 ? '一般' : '不太重要';
}

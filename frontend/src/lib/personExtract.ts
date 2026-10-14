import { MemoryItem } from '@/lib/api';

/** 常见亲属/社交称谓，用于从记忆文本里提取"人物"。 */
const RELATION_WORDS = [
  '女儿', '儿子', '老伴', '爱人', '妻子', '丈夫', '儿媳妇', '儿媳', '女婿',
  '孙子', '孙女', '外孙女', '外孙', '父亲', '母亲', '爸爸', '妈妈', '公公', '婆婆',
  '哥哥', '弟弟', '姐姐', '妹妹', '老友', '老同事', '同事', '邻居', '朋友', '战友', '同学',
];

const RELATION_RE = new RegExp(`(${RELATION_WORDS.join('|')})([\\u4e00-\\u9fa5]{0,3})`);

export interface PersonNode {
  /** 展示标签，如「女儿小芳」「老伴」 */
  label: string;
  /** 去重键 */
  key: string;
  memories: MemoryItem[];
}

/**
 * 从长期记忆里提取「人物」及其相关记忆。
 * 仅对家人/社交类记忆，或文本包含亲属称谓的记忆生效（启发式，够用即可）。
 */
export function extractPersons(memories: MemoryItem[]): PersonNode[] {
  const map = new Map<string, PersonNode>();
  for (const m of memories) {
    const isPersonType = m.memory_type === 'family' || m.memory_type === 'social';
    const match = RELATION_RE.exec(m.content);
    if (!match) continue;
    if (!isPersonType && !RELATION_WORDS.includes(match[1])) continue;
    const label = match[1] + (match[2] || '');
    if (!map.has(label)) map.set(label, { label, key: label, memories: [] });
    map.get(label)!.memories.push(m);
  }
  return Array.from(map.values()).sort((a, b) => b.memories.length - a.memories.length);
}

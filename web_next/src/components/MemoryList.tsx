'use client';

import { MemoryItem } from '@/lib/api';
import {
  MEMORY_TYPE_ORDER,
  memoryTypeIcon,
  memoryTypeLabel,
  importanceStars,
  importanceText,
} from '@/lib/memoryLabels';

interface Props {
  memories: MemoryItem[];
  onDelete?: (id: number) => void;
}

/**
 * 记忆列表：按「家人 / 人生经历 / 兴趣爱好 …」分组，组内按重要度降序，
 * 重要度用星级 + 文字展示（后端是 0~1 小数，老人看不懂原始数值）。
 */
export function MemoryList({ memories, onDelete }: Props) {
  if (!memories || memories.length === 0) {
    return <p className="text-gray-500">还没有记忆，多和 AI 聊聊吧 🌻</p>;
  }

  const groups = new Map<string, MemoryItem[]>();
  for (const m of memories) {
    const type = (MEMORY_TYPE_ORDER as readonly string[]).includes(m.memory_type)
      ? m.memory_type
      : 'general';
    if (!groups.has(type)) groups.set(type, []);
    groups.get(type)!.push(m);
  }

  const orderedTypes = MEMORY_TYPE_ORDER.filter((t) => groups.has(t));

  return (
    <div className="space-y-5">
      {orderedTypes.map((type) => {
        const items = [...groups.get(type)!].sort(
          (a, b) => (b.importance || 0) - (a.importance || 0)
        );
        return (
          <div key={type}>
            <h3 className="text-base font-bold text-gray-800 mb-2 flex items-center gap-2">
              <span>{memoryTypeIcon(type)}</span>
              {memoryTypeLabel(type)}
              <span className="text-sm font-normal text-gray-500">（{items.length}）</span>
            </h3>
            <ul className="space-y-2">
              {items.map((m) => {
                const stars = importanceStars(m.importance);
                return (
                  <li
                    key={m.id}
                    className="flex items-start gap-3 bg-warm-light/40 rounded-xl p-4"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-gray-900 break-words">{m.content}</p>
                      <p className="text-sm text-gray-500 mt-1">
                        <span title={`重要度：${importanceText(m.importance)}`}>
                          {'⭐'.repeat(stars)}
                        </span>
                        <span className="ml-2">{importanceText(m.importance)}</span>
                        <span className="mx-1">·</span>
                        {new Date(m.created_at).toLocaleDateString('zh-CN')}
                      </p>
                    </div>
                    {onDelete && (
                      <button
                        onClick={() => onDelete(m.id)}
                        className="min-h-[48px] min-w-[48px] rounded-xl bg-red-100 hover:bg-red-200 text-red-600 flex items-center justify-center flex-shrink-0"
                        aria-label="删除这条记忆"
                        title="删除"
                      >
                        🗑
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

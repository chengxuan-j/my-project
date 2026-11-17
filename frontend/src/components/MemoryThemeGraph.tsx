'use client';

import type { MemoryGraph } from '@/lib/api';

const PERSON_X = 110;
const TOPIC_X = 570;
const ROW_H = 34;
const TOP_PAD = 30;

/** 人物节点：琥珀色系；话题节点：暖棕色系，大小随出现次数增长 */
function personR(count: number, max: number): number {
  return 16 + (max > 0 ? (count / max) * 8 : 0);
}
function topicR(count: number, max: number): number {
  return 13 + (max > 0 ? (count / max) * 7 : 0);
}

export function MemoryThemeGraph({ graph }: { graph: MemoryGraph | null }) {
  const persons = graph?.persons ?? [];
  const topics = graph?.topics ?? [];
  const edges = graph?.edges ?? [];

  if (!graph || (persons.length === 0 && topics.length === 0)) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        记忆还太少，聊得越多，这里的人物和话题网络就越清晰 🕸
      </div>
    );
  }

  const rows = Math.max(persons.length, topics.length, 1);
  const height = TOP_PAD * 2 + rows * ROW_H;

  const personMax = Math.max(...persons.map((p) => p.count), 1);
  const topicMax = Math.max(...topics.map((t) => t.count), 1);
  const edgeMax = Math.max(...edges.map((e) => e.count), 1);

  const personY = new Map<string, number>();
  persons.forEach((p, i) => {
    personY.set(p.label, TOP_PAD + i * ROW_H + (rows - persons.length) * ROW_H / 2);
  });
  const topicY = new Map<string, number>();
  topics.forEach((t, i) => {
    topicY.set(t.label, TOP_PAD + i * ROW_H + (rows - topics.length) * ROW_H / 2);
  });

  const edgeOf = (person: string, topic: string) =>
    edges.find((e) => e.person === person && e.topic === topic);

  return (
    <div className="bg-white rounded-2xl p-5 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900">🕸 记忆主题图谱</h3>
      <p className="text-sm text-gray-500 mt-1 mb-2">
        从 {graph.memory_count} 条长期记忆里抽出的人物与话题，连线表示两者被同时提到。
        只看得到词与次数，看不到记忆原文。
      </p>

      <svg viewBox={`0 0 680 ${height}`} className="w-full" role="img" aria-label="记忆主题图谱">
        <title>记忆主题图谱</title>
        {/* 共现连线 */}
        {persons.map((p) =>
          topics.map((t) => {
            const e = edgeOf(p.label, t.label);
            if (!e) return null;
            const y1 = personY.get(p.label)!;
            const y2 = topicY.get(t.label)!;
            const midX = (PERSON_X + TOPIC_X) / 2;
            return (
              <path
                key={`e-${p.label}-${t.label}`}
                d={`M ${PERSON_X} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${TOPIC_X} ${y2}`}
                fill="none"
                stroke="#D97706"
                strokeWidth={1 + (e.count / edgeMax) * 2.5}
                strokeOpacity={0.35 + (e.count / edgeMax) * 0.45}
              >
                <title>{`${p.label} × ${t.label}：${e.count} 条记忆同时提到`}</title>
              </path>
            );
          })
        )}

        {/* 列标题 */}
        <text x={PERSON_X} y={14} textAnchor="middle" fontSize={12} fill="#5F5E5A">人物</text>
        <text x={TOPIC_X} y={14} textAnchor="middle" fontSize={12} fill="#5F5E5A">话题</text>

        {/* 人物节点 */}
        {persons.map((p) => {
          const y = personY.get(p.label)!;
          const r = personR(p.count, personMax);
          return (
            <g key={`p-${p.label}`}>
              <circle cx={PERSON_X} cy={y} r={r} fill="#FEF3C7" stroke="#D97706" strokeWidth={1.5}>
                <title>{`${p.label}：${p.count} 条记忆`}</title>
              </circle>
              <text x={PERSON_X} y={y + 4} textAnchor="middle" fontSize={11} fill="#92400E">
                {p.label.length > 4 ? `${p.label.slice(0, 4)}…` : p.label}
              </text>
              <text x={PERSON_X + r + 6} y={y + 4} fontSize={11} fill="#888780">
                {p.count}
              </text>
            </g>
          );
        })}

        {/* 话题节点 */}
        {topics.map((t) => {
          const y = topicY.get(t.label)!;
          const r = topicR(t.count, topicMax);
          return (
            <g key={`t-${t.label}`}>
              <circle cx={TOPIC_X} cy={y} r={r} fill="#FAEEDA" stroke="#B45309" strokeWidth={1.5}>
                <title>{`${t.label}：${t.count} 条记忆`}</title>
              </circle>
              <text x={TOPIC_X} y={y + 4} textAnchor="middle" fontSize={11} fill="#633806">
                {t.label.length > 4 ? `${t.label.slice(0, 4)}…` : t.label}
              </text>
              <text x={TOPIC_X - r - 6} y={y + 4} textAnchor="end" fontSize={11} fill="#888780">
                {t.count}
              </text>
            </g>
          );
        })}
      </svg>

      <p className="text-xs text-gray-400 mt-2">
        节点越大出现次数越多；连线越粗同时提到的次数越多。悬停节点可看具体次数。
      </p>
    </div>
  );
}

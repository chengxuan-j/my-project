'use client';

import { PersonNode } from '@/lib/personExtract';

interface Props {
  persons: PersonNode[];
  centerLabel: string;
  selected?: string | null;
  onSelect?: (person: PersonNode) => void;
}

/** 人物关系网络：以老人为中心，把记忆里的人物画成辐射网络，点击查看相关记忆。 */
export function PersonNetwork({ persons, centerLabel, selected, onSelect }: Props) {
  if (persons.length === 0) return null;

  const top = persons.slice(0, 8);
  const size = 320;
  const cx = size / 2;
  const cy = size / 2;
  const radius = 110;

  const nodes = top.map((p, i) => {
    const angle = (2 * Math.PI * i) / top.length - Math.PI / 2;
    return {
      ...p,
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
    };
  });

  return (
    <div className="bg-white rounded-2xl shadow-sm border-2 border-warm-light p-4">
      <h3 className="text-lg font-bold text-gray-900 mb-1">🕸 人物关系网络</h3>
      <p className="text-sm text-gray-500 mb-2">点一点人物，看看 AI 记住的关于他/她的事</p>

      <svg viewBox={`0 0 ${size} ${size}`} className="w-full max-w-[360px] mx-auto">
        {nodes.map((n) => (
          <line
            key={`l-${n.key}`}
            x1={cx}
            y1={cy}
            x2={n.x}
            y2={n.y}
            stroke="#FCD34D"
            strokeWidth={2}
          />
        ))}

        {/* 中心：老人 */}
        <circle cx={cx} cy={cy} r={36} fill="#F59E0B" />
        <text
          x={cx}
          y={cy + 5}
          textAnchor="middle"
          fontSize={15}
          fill="#fff"
          fontWeight="bold"
        >
          {centerLabel.slice(0, 4)}
        </text>

        {/* 周围：人物 */}
        {nodes.map((n) => {
          const active = selected === n.key;
          return (
            <g
              key={n.key}
              onClick={() => onSelect?.(n)}
              style={{ cursor: 'pointer' }}
            >
              <circle
                cx={n.x}
                cy={n.y}
                r={26}
                fill={active ? '#F59E0B' : '#FEF3C7'}
                stroke="#F59E0B"
                strokeWidth={2}
              />
              <text
                x={n.x}
                y={n.y + 5}
                textAnchor="middle"
                fontSize={12}
                fill={active ? '#fff' : '#92400E'}
              >
                {n.label.slice(0, 4)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap gap-2 mt-2 justify-center">
        {top.map((n) => (
          <button
            key={n.key}
            type="button"
            onClick={() => onSelect?.(n)}
            className={`px-3 py-1 rounded-lg text-sm border-2 ${
              selected === n.key
                ? 'bg-warm-primary text-white border-warm-primary'
                : 'bg-warm-light text-gray-700 border-warm-light'
            }`}
          >
            {n.label}（{n.memories.length}）
          </button>
        ))}
      </div>
    </div>
  );
}

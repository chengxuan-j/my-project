'use client';

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { EmotionTrendDay } from '@/lib/api';
import { EMOTION_LABEL } from '@/components/EmotionChart';

const EMOTION_COLOR: Record<string, string> = {
  happy: '#22C55E',
  sad: '#3B82F6',
  anxious: '#F59E0B',
  lonely: '#8B5CF6',
  calm: '#06B6D4',
  angry: '#EF4444',
  neutral: '#9CA3AF',
  bored: '#A855F7',
  tired: '#64748B',
  nostalgic: '#EC4899',
  grateful: '#10B981',
  worried: '#F97316',
};

interface Props {
  trend: EmotionTrendDay[];
}

export function EmotionTrendChart({ trend }: Props) {
  const arr = Array.isArray(trend) ? trend : [];
  // trend 已按日期降序，图表从旧到新更直观
  const data = [...arr]
    .sort((a, b) => (a.date < b.date ? -1 : 1))
    .map((d) => ({
      date: d.date.slice(5), // MM-DD
      avg_intensity: d.avg_intensity,
      dominant_emotion: d.dominant_emotion,
      emotionCn: EMOTION_LABEL[d.dominant_emotion] || d.dominant_emotion,
      count: d.record_count,
    }));

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        这段时间还没有情绪记录 🗓
      </div>
    );
  }

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900 mb-3">📅 每日情绪概览</h3>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#FDE68A" />
          <XAxis dataKey="date" tick={{ fontSize: 14 }} />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 14 }}
          />
          <Tooltip
            contentStyle={{ fontSize: 16, borderRadius: 12 }}
            formatter={(value: number, _name: string, item: { payload?: { emotionCn?: string; count?: number } }) => [
              `${Math.round((value as number) * 100)}%（${item.payload?.emotionCn || ''}，共 ${item.payload?.count ?? 0} 次）`,
              '平均强度',
            ]}
          />
          <Bar
            dataKey="avg_intensity"
            radius={[6, 6, 0, 0]}
            // 每天柱子按其主导情绪着色
            fillOpacity={0.9}
            shape={(props: { x?: number; y?: number; width?: number; height?: number; payload?: { dominant_emotion?: string } }) => {
              const { x, y, width, height, payload } = props;
              if (x == null || y == null || width == null || height == null) return <g />;
              const color = EMOTION_COLOR[payload?.dominant_emotion || 'neutral'] || '#9CA3AF';
              return <rect x={x} y={y} width={width} height={height} rx={6} fill={color} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-sm text-gray-500 mt-3">
        每天一根柱子代表当天的平均情绪强度，颜色对应当天出现最多的情绪。
      </p>
    </div>
  );
}

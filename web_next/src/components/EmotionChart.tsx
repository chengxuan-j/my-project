'use client';

import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { EmotionRecord } from '@/lib/api';

export const EMOTION_LABEL: Record<string, string> = {
  happy: '开心',
  sad: '难过',
  anxious: '焦虑',
  lonely: '孤单',
  calm: '平静',
  angry: '生气',
  neutral: '平静',
  bored: '无聊',
  tired: '疲惫',
  nostalgic: '怀念',
  grateful: '感激',
  worried: '担忧',
};

// 各情绪对应的颜色，用于给折线上的圆点上色
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
  records: EmotionRecord[];
}

export function EmotionChart({ records }: Props) {
  // 按时间升序 + 格式化；intensity 后端为 0~1 的小数
  const data = [...records]
    .sort(
      (a, b) =>
        new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
    )
    .map((r) => ({
      time: new Date(r.created_at).toLocaleString('zh-CN', {
        month: 'numeric',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }),
      intensity: r.intensity,
      emotion: r.emotion,
      emotionCn: EMOTION_LABEL[r.emotion] || r.emotion,
    }));

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        还没有情绪记录，先和 AI 聊聊天吧 💬
      </div>
    );
  }

  // 只列出数据中实际出现的情绪，避免图例过长
  const usedEmotions = Array.from(new Set(data.map((d) => d.emotion)));

  return (
    <div className="bg-white rounded-2xl p-4 shadow-sm border border-warm-light">
      <h3 className="text-lg font-bold text-gray-900 mb-3">📈 情绪强度趋势</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#FDE68A" />
          <XAxis dataKey="time" tick={{ fontSize: 14 }} />
          {/* intensity 量纲为 0~1，Y 轴改用百分比展示 */}
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 14 }}
          />
          <Tooltip
            contentStyle={{ fontSize: 16, borderRadius: 12 }}
            formatter={(value: number, _name: string, item: { payload?: { emotionCn?: string } }) => [
              `${Math.round((value as number) * 100)}%（${item.payload?.emotionCn || ''}）`,
              '情绪强度',
            ]}
          />
          <Line
            type="monotone"
            dataKey="intensity"
            stroke="#F59E0B"
            strokeWidth={3}
            // 圆点按当时情绪着色，让「情绪」字段真正被消费
            dot={(props: { cx?: number; cy?: number; payload?: { emotion?: string } }) => {
              const { cx, cy, payload } = props;
              if (cx == null || cy == null) return <g />;
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={EMOTION_COLOR[payload?.emotion || 'neutral'] || '#F59E0B'}
                  stroke="#fff"
                  strokeWidth={1}
                />
              );
            }}
            activeDot={{ r: 8 }}
          />
        </LineChart>
      </ResponsiveContainer>

      {/* 情绪颜色图例 */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-3">
        {usedEmotions.map((e) => (
          <span key={e} className="inline-flex items-center gap-1.5 text-sm text-gray-600">
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{ backgroundColor: EMOTION_COLOR[e] || '#9CA3AF' }}
            />
            {EMOTION_LABEL[e] || e}
          </span>
        ))}
      </div>
    </div>
  );
}

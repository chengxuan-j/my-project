'use client';

import {
  PieChart,
  Pie,
  Cell,
  Legend,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
} from 'recharts';
import type { EmotionRecord } from '@/lib/api';
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

/** 家属端情绪洞察：情绪分布环形图 + 活跃时段分布，帮助了解老人何时最需要陪伴。 */
export function EmotionInsights({ records }: { records: EmotionRecord[] }) {
  if (!records || records.length === 0) {
    return (
      <div className="bg-white rounded-2xl p-8 text-center text-gray-500 border border-warm-light">
        还没有足够的数据做洞察 📊
      </div>
    );
  }

  const emoCount = new Map<string, number>();
  const hourCount = new Array<number>(24).fill(0);
  for (const r of records) {
    emoCount.set(r.emotion, (emoCount.get(r.emotion) || 0) + 1);
    const h = new Date(r.created_at).getHours();
    if (h >= 0 && h < 24) hourCount[h] += 1;
  }

  const pieData = Array.from(emoCount.entries())
    .map(([emotion, count]) => ({
      emotion,
      name: EMOTION_LABEL[emotion] || emotion,
      value: count,
    }))
    .sort((a, b) => b.value - a.value);

  const hourData = hourCount.map((count, h) => ({ hour: `${h}时`, count }));

  return (
    <div className="space-y-4">
      <div className="bg-white rounded-2xl p-4 shadow-sm border border-warm-light">
        <h3 className="text-lg font-bold text-gray-900 mb-3">🍩 情绪分布</h3>
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={pieData}
              dataKey="value"
              nameKey="name"
              innerRadius={50}
              outerRadius={90}
              paddingAngle={2}
            >
              {pieData.map((d, i) => (
                <Cell key={i} fill={EMOTION_COLOR[d.emotion] || '#9CA3AF'} />
              ))}
            </Pie>
            <Tooltip formatter={(v: number) => [`${v} 次`, '出现次数']} />
            <Legend wrapperStyle={{ fontSize: 14 }} />
          </PieChart>
        </ResponsiveContainer>
        <p className="text-sm text-gray-500 mt-2">最近记录中各情绪的比例，占比最高的情绪最需要关注。</p>
      </div>

      <div className="bg-white rounded-2xl p-4 shadow-sm border border-warm-light">
        <h3 className="text-lg font-bold text-gray-900 mb-3">🕐 活跃时段</h3>
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={hourData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#FDE68A" />
            <XAxis dataKey="hour" tick={{ fontSize: 12 }} interval={2} />
            <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
            <Tooltip formatter={(v: number) => [`${v} 次`, '交流次数']} />
            <Bar dataKey="count" fill="#F59E0B" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
        <p className="text-sm text-gray-500 mt-2">
          柱子越高的时段，老人越常交流；这几个时段多陪陪他/她，效果最好。
        </p>
      </div>
    </div>
  );
}

'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { journeyApi, Journey, Portrait } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { GrowthChart } from '@/components/GrowthChart';
import { LifeRiver } from '@/components/LifeRiver';
import { PortraitCard } from '@/components/PortraitCard';

/** 老人端「人生河」：AI 对自己的了解在增长 + 一生回忆汇成的河。 */
export default function JourneyPage() {
  const { accessToken, user } = useAuthStore();
  const [journey, setJourney] = useState<Journey | null>(null);
  const [portrait, setPortrait] = useState<Portrait | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!accessToken) return;
    journeyApi
      .me()
      .then(setJourney)
      .catch((err) => setError(err instanceof Error ? err.message : '加载失败'))
      .finally(() => setLoading(false));
    // 画像卡失败不阻塞主页面
    journeyApi.portrait().then(setPortrait).catch(() => setPortrait(null));
  }, [accessToken]);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center text-gray-500 text-lg">
        正在汇集你的人生之河…
      </div>
    );
  }

  if (error || !journey) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-12 text-center text-gray-500">
        <p className="text-lg">这条河还没加载出来</p>
        <p className="text-sm mt-2">{error || '稍后再试试'}</p>
      </div>
    );
  }

  const name = journey.elderly_name || user?.name || '你';

  return (
    <div className="max-w-4xl mx-auto px-4 py-6 space-y-5">
      <div className="flex items-end justify-between gap-4 flex-wrap">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.18em] text-amber-600">你的人生，值得被记住</p>
          <h1 className="text-3xl font-bold text-gray-900 mt-1">🌊 {name}的人生河</h1>
          <p className="text-gray-500 mt-1">
            这一页看的是「变化」：AI 对你的理解、这些年的心情起伏。
            完整故事在《人生之书》里读。
          </p>
        </div>
        <Link
          href="/book"
          className="min-h-[48px] px-4 rounded-xl bg-warm-primary text-white font-bold flex items-center hover:bg-warm-dark"
        >
          📗 看我的人生之书
        </Link>
      </div>

      <PortraitCard portrait={portrait} />

      <GrowthChart
        months={journey.growth_months}
        total={journey.memory_count}
        daysTogether={journey.days_together}
        thisMonth={journey.this_month_memories}
      />

      <LifeRiver stages={journey.river_stages} total={journey.river_total} />
    </div>
  );
}

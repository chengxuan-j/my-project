'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { journeyApi, Journey, Portrait } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { GrowthChart } from '@/components/GrowthChart';
import { LifeRiver } from '@/components/LifeRiver';
import { PortraitCard } from '@/components/PortraitCard';
import { PageHeader } from '@/components/ui/PageHeader';
import { EmptyState } from '@/components/ui/EmptyState';
import { BookOpen, Waves } from 'lucide-react';

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
      <div className="max-w-4xl mx-auto px-4 py-12 text-center text-muted text-lg">
        正在汇集你的人生之河…
      </div>
    );
  }

  if (error || !journey) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-6">
        <PageHeader
          eyebrow="你的人生，值得被记住"
          title="人生河"
          description="这一页看的是「变化」：AI 对你的理解、这些年的心情起伏。"
          icon={<Waves aria-hidden className="h-7 w-7 text-primary" />}
        />
        <EmptyState
          icon={<Waves aria-hidden className="h-6 w-6" />}
          title="这条河还没加载出来"
          description={error || '稍后再试试'}
        />
      </div>
    );
  }

  const name = journey.elderly_name || user?.name || '你';

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      <PageHeader
        eyebrow="你的人生，值得被记住"
        title={`${name}的人生河`}
        description="这一页看的是「变化」：AI 对你的理解、这些年的心情起伏。完整故事在《人生之书》里读。"
        icon={<Waves aria-hidden className="h-7 w-7 text-primary" />}
        actions={
          <Link
            href="/book"
            className="min-h-[44px] px-4 rounded-btn bg-primary text-on-primary shadow-btn font-bold flex items-center gap-1.5 hover:bg-primary-strong"
          >
            <BookOpen aria-hidden className="h-5 w-5" />
            看我的人生之书
          </Link>
        }
      />

      <div className="grid lg:grid-cols-[320px_1fr] gap-5 items-start">
        <PortraitCard portrait={portrait} />
        <GrowthChart
          months={journey.growth_months}
          total={journey.memory_count}
          daysTogether={journey.days_together}
          thisMonth={journey.this_month_memories}
        />
      </div>

      <LifeRiver stages={journey.river_stages} total={journey.river_total} />
    </div>
  );
}

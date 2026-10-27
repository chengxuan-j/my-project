'use client';

import { useEffect, useState } from 'react';
import {
  FamilyHealthSummary,
  FamilyLetter,
  familyApi,
  HealthRecordItem,
} from '@/lib/api';

const LEVEL_CLS: Record<string, string> = {
  green: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  amber: 'bg-amber-50 text-amber-700 border-amber-200',
  orange: 'bg-orange-50 text-orange-700 border-orange-200',
  red: 'bg-rose-50 text-rose-700 border-rose-200',
  blue: 'bg-sky-50 text-sky-700 border-sky-200',
  gray: 'bg-gray-50 text-gray-600 border-gray-200',
};

function fmt(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function RecordRow({ r }: { r: HealthRecordItem }) {
  return (
    <li className="py-2 flex items-center justify-between gap-3 flex-wrap">
      <span className="text-gray-700">
        {fmt(r.measured_at)} · {r.record_label}
        {r.record_type === 'blood_pressure'
          ? ` ${r.systolic}/${r.diastolic} mmHg`
          : ` ${r.value ?? '-'} ${r.unit}`}
        {r.pulse ? ` · 心跳 ${r.pulse}` : ''}
        {r.note ? ` · ${r.note}` : ''}
      </span>
      <span className={`rounded-full border px-2 py-0.5 text-sm ${LEVEL_CLS[r.level.color] || LEVEL_CLS.gray}`}>
        {r.level.label}
      </span>
    </li>
  );
}

/**
 * 家属端关怀面板（只读）。
 *
 * 刻意不提供任何"替老人改"的入口：用药与复诊是老人自己的事，
 * 家属看见就好，改了而不告诉老人反而危险。
 */
export function FamilyCarePanel({
  elderlyId,
  elderlyName,
}: {
  elderlyId: string;
  elderlyName: string;
}) {
  const [health, setHealth] = useState<FamilyHealthSummary | null>(null);
  const [letters, setLetters] = useState<FamilyLetter[]>([]);
  const [scheduledCount, setScheduledCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all([
      familyApi.healthCare(elderlyId).catch(() => null),
      familyApi.letters(elderlyId).catch(() => ({ letters: [], scheduled_count: 0 })),
    ]).then(([h, l]) => {
      if (!alive) return;
      setHealth(h);
      setLetters(l.letters || []);
      setScheduledCount(l.scheduled_count || 0);
      setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [elderlyId]);

  if (loading) {
    return <p className="text-gray-500 py-6">正在加载{elderlyName}的健康关怀…</p>;
  }

  return (
    <section className="space-y-4">
      {/* 概览 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-2xl border-2 border-warm-light p-4">
          <p className="text-sm text-gray-500">近 7 天吃药</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {health?.adherence.rate == null
              ? '—'
              : `${Math.round(health.adherence.rate * 100)}%`}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {health
              ? `确认 ${health.adherence.acknowledged}/${health.adherence.expected} 次`
              : '暂无计划'}
          </p>
        </div>
        <div className="bg-white rounded-2xl border-2 border-warm-light p-4">
          <p className="text-sm text-gray-500">现在待办</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{health?.due.length ?? 0}</p>
          <p className="text-xs text-gray-500 mt-1">药 / 复诊提醒未确认</p>
        </div>
        <div className="bg-white rounded-2xl border-2 border-warm-light p-4">
          <p className="text-sm text-gray-500">最近血压</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {health?.latest_blood_pressure
              ? `${health.latest_blood_pressure.systolic}/${health.latest_blood_pressure.diastolic}`
              : '—'}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {health?.latest_blood_pressure
              ? `${health.latest_blood_pressure.level.label} · ${fmt(
                  health.latest_blood_pressure.measured_at
                )}`
              : '还没有记录'}
          </p>
        </div>
        <div className="bg-white rounded-2xl border-2 border-warm-light p-4">
          <p className="text-sm text-gray-500">在吃的药</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">
            {health?.medications.length ?? 0}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {health?.appointments.length
              ? `近期待复诊 ${health.appointments.length} 次`
              : '近期没有复诊'}
          </p>
        </div>
      </div>

      {health && health.due.length > 0 && (
        <div className="bg-amber-50 border-2 border-amber-300 rounded-2xl p-4">
          <p className="font-bold text-gray-900">⏰ 现在有待办</p>
          <ul className="mt-2 space-y-1 text-gray-700">
            {health.due.map((d) => (
              <li key={d.key}>
                {d.kind === 'medication' ? '💊 ' : '🏥 '}
                {d.title}
                {d.detail ? ` · ${d.detail}` : ''} · {fmt(d.scheduled_for)}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 用药与复诊 */}
        <div className="bg-white rounded-2xl border-2 border-warm-light p-5">
          <h3 className="text-lg font-bold text-gray-900">💊 用药与复诊</h3>
          {!health || (health.medications.length === 0 && health.appointments.length === 0) ? (
            <p className="text-gray-500 mt-2">还没有记录。</p>
          ) : (
            <>
              {health.medications.length > 0 && (
                <ul className="mt-3 space-y-2">
                  {health.medications.map((m) => (
                    <li key={m.id} className="text-gray-800">
                      <span className="font-medium">{m.name}</span>
                      <span className="text-sm text-gray-500 ml-2">
                        {[m.times.join('、'), m.dosage, m.note].filter(Boolean).join(' · ')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {health.appointments.length > 0 && (
                <ul className="mt-3 pt-3 border-t border-warm-light space-y-2">
                  {health.appointments.map((a) => (
                    <li key={a.id} className="text-gray-800">
                      🏥 <span className="font-medium">{a.title}</span>
                      <span className="text-sm text-gray-500 ml-2">
                        {[fmt(a.appointment_at), a.hospital, a.department]
                          .filter(Boolean)
                          .join(' · ')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>

        {/* 血压等记录 */}
        <div className="bg-white rounded-2xl border-2 border-warm-light p-5">
          <h3 className="text-lg font-bold text-gray-900">🩺 最近记录</h3>
          {!health || health.records.length === 0 ? (
            <p className="text-gray-500 mt-2">老人还没有记录过。</p>
          ) : (
            <ul className="mt-2 divide-y divide-warm-light">
              {health.records.slice(0, 6).map((r) => (
                <RecordRow key={r.id} r={r} />
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* 时光信笺 */}
      <div className="bg-white rounded-2xl border-2 border-warm-light p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h3 className="text-lg font-bold text-gray-900">💌 老人写下的时光信笺</h3>
          {scheduledCount > 0 && (
            <span className="text-sm text-gray-500">
              还有 {scheduledCount} 封写给家人的信，没到日子
            </span>
          )}
        </div>
        {letters.length === 0 ? (
          <p className="text-gray-500 mt-2">
            还没有可看的信。只显示老人明确写了"家人也能看"、且已经到日子的信。
          </p>
        ) : (
          <ul className="mt-3 space-y-3">
            {letters.map((l) => (
              <li key={l.id} className="rounded-xl bg-warm-light/30 border border-warm-light p-4">
                <p className="font-bold text-gray-900">
                  {l.title || '一封信'}
                  <span className="ml-2 text-sm font-normal text-gray-500">
                    写给{l.recipient_name || '家人'} · {fmt(l.deliver_at)} 打开
                  </span>
                </p>
                <p className="mt-2 text-gray-800 whitespace-pre-wrap leading-relaxed">
                  {l.content}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

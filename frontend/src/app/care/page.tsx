'use client';

import { FormEvent, useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BellRing, CalendarCheck, CheckCircle2, Heart, Pill, Stethoscope } from 'lucide-react';
import { PageHeader } from '@/components/ui/PageHeader';
import {
  ApiError,
  HealthAppointment,
  HealthMedication,
  HealthOverview,
  healthCareApi,
} from '@/lib/api';
import { useAuthStore } from '@/stores/auth';
import { useCareStore } from '@/stores/care';
import { useServerEvents } from '@/lib/events';
import { LargeButton } from '@/components/LargeButton';

const LEVEL_CLS: Record<string, string> = {
  green: 'bg-success-soft text-success border-hairline',
  amber: 'bg-warning-soft text-warning border-hairline',
  orange: 'bg-warning-soft text-warning border-hairline',
  red: 'bg-accent-soft text-danger border-hairline',
  blue: 'bg-lilac-soft text-primary border-hairline',
  gray: 'bg-card-soft text-muted border-hairline',
};

const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日'];

function fmtTime(iso: string): string {
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

function fmtDay(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' });
}

function freqText(m: HealthMedication): string {
  if (m.frequency === 'as_needed') return '按需服用';
  if (m.frequency === 'weekly') {
    const days = (m.weekdays || []).map((d) => `周${WEEK_LABELS[d] ?? d}`).join('、');
    return days ? `每周 ${days}` : '每周';
  }
  return '每天';
}

const inputCls =
  'w-full min-h-[52px] rounded-btn border border-hairline px-4 text-lg text-ink ' +
  'focus:outline-none focus:border-primary bg-card';

/** 老人端「健康关怀」：今天该做什么 + 用药/复诊/血压记录。 */
export default function CarePage() {
  const router = useRouter();
  const accessToken = useAuthStore((s) => s.accessToken);
  const user = useAuthStore((s) => s.user);
  const showPreview = useCareStore((s) => s.showPreview);

  const [hydrated, setHydrated] = useState(false);
  const [data, setData] = useState<HealthOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyKey, setBusyKey] = useState('');

  // 血压表单
  const [systolic, setSystolic] = useState('');
  const [diastolic, setDiastolic] = useState('');
  const [pulse, setPulse] = useState('');
  const [recordNote, setRecordNote] = useState('');

  // 用药表单
  const [showMedForm, setShowMedForm] = useState(false);
  const [medName, setMedName] = useState('');
  const [medDosage, setMedDosage] = useState('');
  const [medTimes, setMedTimes] = useState('08:00');
  const [medNote, setMedNote] = useState('');

  // 复诊表单
  const [showApptForm, setShowApptForm] = useState(false);
  const [apptTitle, setApptTitle] = useState('');
  const [apptHospital, setApptHospital] = useState('');
  const [apptDept, setApptDept] = useState('');
  const [apptAt, setApptAt] = useState('');

  useEffect(() => setHydrated(true), []);

  useEffect(() => {
    if (!hydrated) return;
    if (!accessToken) {
      router.push('/login');
      return;
    }
    if (user?.role === 'family') {
      router.push('/family');
    }
  }, [hydrated, accessToken, user, router]);

  const load = useCallback(async () => {
    try {
      setData(await healthCareApi.overview());
      setError('');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '加载失败，稍后再试试');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!hydrated || !accessToken || user?.role === 'family') return;
    load();
  }, [hydrated, accessToken, user, load]);

  // 后端定时扫描到"该吃药了"会推 SSE，页面在开着就立刻刷新
  useServerEvents(
    accessToken,
    (e) => {
      if (e.type === 'health_reminder') load();
    },
    user?.role === 'elderly'
  );

  if (!hydrated || !accessToken) return null;

  const handleAck = async (key: string, kind: string, refId: number, scheduledFor: string) => {
    setBusyKey(key);
    try {
      await healthCareApi.ack({ kind, ref_id: refId, scheduled_for: scheduledFor });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '确认失败');
    } finally {
      setBusyKey('');
    }
  };

  const handleSaveBP = async (e: FormEvent) => {
    e.preventDefault();
    setBusyKey('bp');
    setError('');
    try {
      await healthCareApi.createRecord({
        record_type: 'blood_pressure',
        systolic: Number(systolic),
        diastolic: Number(diastolic),
        pulse: pulse ? Number(pulse) : undefined,
        note: recordNote,
      });
      setSystolic('');
      setDiastolic('');
      setPulse('');
      setRecordNote('');
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '记录失败');
    } finally {
      setBusyKey('');
    }
  };

  const handleAddMed = async (e: FormEvent) => {
    e.preventDefault();
    setBusyKey('med');
    setError('');
    try {
      await healthCareApi.createMedication({
        name: medName.trim(),
        dosage: medDosage.trim(),
        times: medTimes
          .split(/[,，\s]+/)
          .map((t) => t.trim())
          .filter(Boolean),
        frequency: 'daily',
        note: medNote.trim(),
      });
      setMedName('');
      setMedDosage('');
      setMedTimes('08:00');
      setMedNote('');
      setShowMedForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败');
    } finally {
      setBusyKey('');
    }
  };

  const handleAddAppt = async (e: FormEvent) => {
    e.preventDefault();
    setBusyKey('appt');
    setError('');
    try {
      await healthCareApi.createAppointment({
        title: apptTitle.trim(),
        hospital: apptHospital.trim(),
        department: apptDept.trim(),
        appointment_at: apptAt,
        remind_before_minutes: 1440,
      });
      setApptTitle('');
      setApptHospital('');
      setApptDept('');
      setApptAt('');
      setShowApptForm(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '添加失败');
    } finally {
      setBusyKey('');
    }
  };

  const removeMed = async (m: HealthMedication) => {
    if (!window.confirm(`把「${m.name}」从用药计划里删掉吗？`)) return;
    setBusyKey(`med-${m.id}`);
    try {
      await healthCareApi.deleteMedication(m.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    } finally {
      setBusyKey('');
    }
  };

  const removeAppt = async (a: HealthAppointment) => {
    if (!window.confirm(`删除「${a.title}」这条复诊安排吗？`)) return;
    setBusyKey(`appt-${a.id}`);
    try {
      await healthCareApi.deleteAppointment(a.id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '删除失败');
    } finally {
      setBusyKey('');
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      <PageHeader
        eyebrow="吃药 · 复诊 · 血压"
        title="健康关怀"
        description="该做的事放在最上面。做完点一下「吃过了」，就不用再惦记。"
        icon={<Heart aria-hidden className="h-7 w-7 text-danger" />}
        actions={
          <LargeButton
            variant="secondary"
            onClick={() =>
              showPreview([
                {
                  key: `preview-${Date.now()}`,
                  kind: 'medication',
                  ref_id: 0,
                  title: '该吃降压药',
                  detail: '演示 · 2 片',
                  scheduled_for: new Date(Date.now() - 3 * 60 * 1000).toISOString(),
                  minutes_until: -3,
                  overdue_minutes: 3,
                  log_status: '',
                  log_id: null,
                  message: '',
                },
              ])
            }
          >
            <BellRing aria-hidden className="h-5 w-5" />
            试一下提醒
          </LargeButton>
        }
      />

      {error && (
        <div className="rounded-btn bg-accent-soft border border-hairline text-danger px-4 py-3">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-center text-muted py-12 text-lg">正在看看今天的安排…</p>
      ) : !data ? (
        <p className="text-center text-muted py-12">暂时加载不出来，稍后再打开看看</p>
      ) : (
        <>
          {/* 现在该做的：有到点未确认的事就用红色强提示，和全局弹窗保持同一套语言 */}
          <section
            className={`rounded-card shadow-card p-5 ${
              data.due.length > 0
                ? 'bg-accent-soft border-4 border-danger'
                : 'bg-card border border-hairline'
            }`}
          >
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <h2
                className={`flex items-center gap-2 text-2xl font-bold ${
                  data.due.length > 0 ? 'text-danger' : 'text-ink'
                }`}
              >
                {data.due.length > 0 ? (
                  <>
                    <span className="relative flex h-3.5 w-3.5" aria-hidden>
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-danger opacity-75" />
                      <span className="relative inline-flex rounded-full h-3.5 w-3.5 bg-danger" />
                    </span>
                    <BellRing aria-hidden className="h-6 w-6" />
                    现在必须处理
                  </>
                ) : (
                  <>
                    <CheckCircle2 aria-hidden className="h-6 w-6 text-success" />
                    现在没有要做的
                  </>
                )}
              </h2>
              <span className="text-sm text-muted">今天 {fmtDay(data.today)}</span>
            </div>

            {data.due.length === 0 ? (
              <p className="text-muted mt-3 text-lg">
                该吃的药、该去复诊的事，都安排好了。到点会全屏弹出来提醒你，还会响三声。
                想起什么就点下面记一笔。
              </p>
            ) : (
              <ul className="mt-4 space-y-3">
                {data.due.map((item) => (
                  <li
                    key={item.key}
                    className="rounded-card border border-hairline bg-card px-4 py-4 flex items-center justify-between gap-4 flex-wrap"
                  >
                    <div className="min-w-0">
                      <p className="text-xl font-bold text-ink">
                        {item.kind === 'medication' ? '💊 ' : '🏥 '}
                        {item.title}
                      </p>
                      <p className="text-ink mt-1">
                        {item.detail || (item.kind === 'medication' ? '记得按时吃' : '记得别迟到')}
                      </p>
                      <p className="text-base font-semibold text-danger mt-1">
                        {item.kind === 'medication'
                          ? `原定 ${fmtTime(item.scheduled_for)}`
                          : `时间 ${fmtTime(item.scheduled_for)}`}
                        {(item.overdue_minutes ?? 0) > 0
                          ? `，已经过了 ${item.overdue_minutes} 分钟`
                          : '，到点了'}
                      </p>
                    </div>
                    <LargeButton
                      size="xl"
                      disabled={busyKey === item.key}
                      onClick={() =>
                        handleAck(item.key, item.kind, item.ref_id, item.scheduled_for)
                      }
                    >
                      {busyKey === item.key
                        ? '记着呢…'
                        : item.kind === 'medication'
                          ? '✅ 我吃过了'
                          : '✅ 我知道了'}
                    </LargeButton>
                  </li>
                ))}
              </ul>
            )}

            {data.upcoming.length > 0 && (
              <div className="mt-5 border-t border-hairline pt-4">
                <p className="text-sm font-semibold text-muted">接下来 24 小时</p>
                <p className="mt-2 text-xl font-bold text-ink">
                  {data.upcoming[0].kind === 'medication' ? '💊 ' : '🏥 '}
                  {data.upcoming[0].title}
                  <span className="ml-2 text-base font-normal text-warning">
                    {fmtTime(data.upcoming[0].scheduled_for)}
                  </span>
                </p>
                <ul className="mt-2 space-y-1.5">
                  {data.upcoming.slice(1, 5).map((item) => (
                    <li key={item.key} className="flex items-center justify-between gap-3 text-ink">
                      <span>
                        {item.kind === 'medication' ? '💊 ' : '🏥 '}
                        {item.title}
                      </span>
                      <span className="text-muted">{fmtTime(item.scheduled_for)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* 血压记录 */}
          {/* 血压 / 用药 / 复诊：桌面端双列排布 */}
          <div className="grid lg:grid-cols-2 gap-5 items-start">
          <section className="bg-card rounded-card shadow-card border border-hairline p-5">
            <h2 className="flex items-center gap-2 text-xl font-bold text-ink"><Stethoscope className="h-5 w-5 text-primary" aria-hidden />记一次血压</h2>
            <p className="text-sm text-muted mt-1">
              量完顺手记一下，日子久了能看出门道。这里只做记录，不当医生。
            </p>
            <form onSubmit={handleSaveBP} className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
              <label className="block">
                <span className="text-sm text-muted">高压</span>
                <input
                  className={inputCls}
                  type="number"
                  inputMode="numeric"
                  required
                  value={systolic}
                  onChange={(e) => setSystolic(e.target.value)}
                  placeholder="120"
                />
              </label>
              <label className="block">
                <span className="text-sm text-muted">低压</span>
                <input
                  className={inputCls}
                  type="number"
                  inputMode="numeric"
                  required
                  value={diastolic}
                  onChange={(e) => setDiastolic(e.target.value)}
                  placeholder="80"
                />
              </label>
              <label className="block">
                <span className="text-sm text-muted">心跳（可不填）</span>
                <input
                  className={inputCls}
                  type="number"
                  inputMode="numeric"
                  value={pulse}
                  onChange={(e) => setPulse(e.target.value)}
                  placeholder="75"
                />
              </label>
              <div className="flex items-end">
                <LargeButton type="submit" size="lg" className="w-full" disabled={busyKey === 'bp'}>
                  {busyKey === 'bp' ? '记着呢…' : '记下来'}
                </LargeButton>
              </div>
              <label className="block col-span-2 sm:col-span-4">
                <span className="text-sm text-muted">备注（可不填）</span>
                <input
                  className={inputCls}
                  value={recordNote}
                  onChange={(e) => setRecordNote(e.target.value)}
                  placeholder="比如：早上起床后量的"
                />
              </label>
            </form>

            {data.latest_blood_pressure && (
              <div className="mt-4 rounded-btn bg-primary-softer border border-hairline px-4 py-3">
                <p className="text-ink">
                  最近一次：{data.latest_blood_pressure.systolic}/
                  {data.latest_blood_pressure.diastolic} mmHg
                  {data.latest_blood_pressure.pulse
                    ? ` · 心跳 ${data.latest_blood_pressure.pulse}`
                    : ''}
                  <span
                    className={`ml-2 inline-block rounded-full border px-2 py-0.5 text-sm ${
                      LEVEL_CLS[data.latest_blood_pressure.level.color] || LEVEL_CLS.gray
                    }`}
                  >
                    {data.latest_blood_pressure.level.label}
                  </span>
                </p>
                {data.latest_blood_pressure.level.advice && (
                  <p className="text-sm text-muted mt-1">
                    {data.latest_blood_pressure.level.advice}
                  </p>
                )}
              </div>
            )}

            {data.records.filter((r) => r.record_type === 'blood_pressure').length > 0 && (
              <ul className="mt-4 divide-y divide-hairline">
                {data.records
                  .filter((r) => r.record_type === 'blood_pressure')
                  .slice(0, 6)
                  .map((r) => (
                    <li key={r.id} className="py-2 flex items-center justify-between gap-3 flex-wrap">
                      <span className="text-ink">
                        {fmtTime(r.measured_at)} · {r.systolic}/{r.diastolic} mmHg
                        {r.pulse ? ` · ${r.pulse}` : ''}
                        {r.note ? ` · ${r.note}` : ''}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 text-sm ${
                          LEVEL_CLS[r.level.color] || LEVEL_CLS.gray
                        }`}
                      >
                        {r.level.label}
                      </span>
                    </li>
                  ))}
              </ul>
            )}
          </section>

          {/* 用药计划 */}
          <section className="bg-card rounded-card shadow-card border border-hairline p-5">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <h2 className="flex items-center gap-2 text-xl font-bold text-ink"><Pill className="h-5 w-5 text-primary" aria-hidden />我在吃的药</h2>
              <LargeButton variant="secondary" onClick={() => setShowMedForm((v) => !v)}>
                {showMedForm ? '收起' : '＋ 加一种药'}
              </LargeButton>
            </div>

            {showMedForm && (
              <form onSubmit={handleAddMed} className="mt-4 space-y-3 rounded-btn bg-primary-softer p-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-sm text-muted">药名</span>
                    <input
                      className={inputCls}
                      required
                      value={medName}
                      onChange={(e) => setMedName(e.target.value)}
                      placeholder="比如：降压药"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">一次吃多少</span>
                    <input
                      className={inputCls}
                      value={medDosage}
                      onChange={(e) => setMedDosage(e.target.value)}
                      placeholder="比如：1 片"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">几点吃（多个时间用逗号隔开）</span>
                    <input
                      className={inputCls}
                      value={medTimes}
                      onChange={(e) => setMedTimes(e.target.value)}
                      placeholder="08:00, 20:00"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">备注（可不填）</span>
                    <input
                      className={inputCls}
                      value={medNote}
                      onChange={(e) => setMedNote(e.target.value)}
                      placeholder="比如：饭后吃"
                    />
                  </label>
                </div>
                <LargeButton type="submit" size="lg" disabled={busyKey === 'med'}>
                  {busyKey === 'med' ? '保存中…' : '存进我的药单'}
                </LargeButton>
              </form>
            )}

            {data.medications.length === 0 ? (
              <p className="text-muted mt-3">还没有记录药。加了之后，到点会提醒你。</p>
            ) : (
              <ul className="mt-4 space-y-3">
                {data.medications.map((m) => (
                  <li
                    key={m.id}
                    className={`rounded-btn border px-4 py-3 flex items-center justify-between gap-3 flex-wrap ${
                      m.active ? 'border-hairline bg-card' : 'border-hairline bg-card-soft opacity-70'
                    }`}
                  >
                    <div>
                      <p className="text-lg font-bold text-ink">
                        {m.name}
                        {!m.active && <span className="ml-2 text-sm text-muted">已停用</span>}
                      </p>
                      <p className="text-muted text-sm mt-0.5">
                        {[freqText(m), m.times.join('、'), m.dosage, m.note]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => removeMed(m)}
                      disabled={busyKey === `med-${m.id}`}
                      className="min-h-[44px] px-3 rounded-lg text-danger hover:bg-accent-soft"
                    >
                      删除
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 复诊 */}
          <section className="bg-card rounded-card shadow-card border border-hairline p-5">
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <h2 className="flex items-center gap-2 text-xl font-bold text-ink"><CalendarCheck className="h-5 w-5 text-primary" aria-hidden />复诊安排</h2>
              <LargeButton variant="secondary" onClick={() => setShowApptForm((v) => !v)}>
                {showApptForm ? '收起' : '＋ 加一次复诊'}
              </LargeButton>
            </div>

            {showApptForm && (
              <form onSubmit={handleAddAppt} className="mt-4 space-y-3 rounded-btn bg-primary-softer p-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <label className="block">
                    <span className="text-sm text-muted">去做什么</span>
                    <input
                      className={inputCls}
                      required
                      value={apptTitle}
                      onChange={(e) => setApptTitle(e.target.value)}
                      placeholder="比如：心内科复诊"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">哪个医院</span>
                    <input
                      className={inputCls}
                      value={apptHospital}
                      onChange={(e) => setApptHospital(e.target.value)}
                      placeholder="比如：市人民医院"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">科室（可不填）</span>
                    <input
                      className={inputCls}
                      value={apptDept}
                      onChange={(e) => setApptDept(e.target.value)}
                      placeholder="比如：心内科"
                    />
                  </label>
                  <label className="block">
                    <span className="text-sm text-muted">什么时候</span>
                    <input
                      className={inputCls}
                      type="datetime-local"
                      required
                      value={apptAt}
                      onChange={(e) => setApptAt(e.target.value)}
                    />
                  </label>
                </div>
                <p className="text-sm text-muted">会提前一天提醒你，不用自己记着。</p>
                <LargeButton type="submit" size="lg" disabled={busyKey === 'appt'}>
                  {busyKey === 'appt' ? '保存中…' : '记下这次复诊'}
                </LargeButton>
              </form>
            )}

            {data.appointments.length === 0 ? (
              <p className="text-muted mt-3">最近没有复诊安排。有的话记上，省得忘。</p>
            ) : (
              <ul className="mt-4 space-y-3">
                {data.appointments.map((a) => (
                  <li
                    key={a.id}
                    className={`rounded-btn border px-4 py-3 flex items-center justify-between gap-3 flex-wrap ${
                      a.status === 'done'
                        ? 'border-hairline bg-card-soft opacity-70'
                        : 'border-hairline bg-card'
                    }`}
                  >
                    <div>
                      <p className="text-lg font-bold text-ink">
                        {a.title}
                        {a.status === 'done' && (
                          <span className="ml-2 text-sm text-muted">已完成</span>
                        )}
                      </p>
                      <p className="text-muted text-sm mt-0.5">
                        {[fmtTime(a.appointment_at), a.hospital, a.department, a.location]
                          .filter(Boolean)
                          .join(' · ')}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      {a.status === 'scheduled' && (
                        <button
                          type="button"
                          onClick={async () => {
                            await healthCareApi.doneAppointment(a.id).catch(() => null);
                            await load();
                          }}
                          className="min-h-[44px] px-3 rounded-lg text-success hover:bg-success-soft"
                        >
                          去过了
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => removeAppt(a)}
                        disabled={busyKey === `appt-${a.id}`}
                        className="min-h-[44px] px-3 rounded-lg text-danger hover:bg-accent-soft"
                      >
                        删除
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
          </div>
        </>
      )}
    </div>
  );
}

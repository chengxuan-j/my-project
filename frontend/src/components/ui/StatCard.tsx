import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: ReactNode;
  unit?: string;
  /** 变化说明，如「比上周多 2」 */
  hint?: ReactNode;
  icon?: ReactNode;
  /** 数值语义色 */
  tone?: 'ink' | 'primary' | 'success' | 'danger' | 'warning';
}

const VALUE_CLS: Record<NonNullable<Props['tone']>, string> = {
  ink: 'text-ink',
  primary: 'text-primary',
  success: 'text-success',
  danger: 'text-danger',
  warning: 'text-warning',
};

/** 指标卡：数字 + 单位 + 说明，仪表盘/关怀页共用。 */
export function StatCard({ label, value, unit, hint, icon, tone = 'ink' }: Props) {
  return (
    <div className="bg-card rounded-card shadow-card border border-hairline p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-muted">{label}</p>
        {icon && <span className="text-faint">{icon}</span>}
      </div>
      <p className={`mt-2 text-3xl font-bold tabular-nums ${VALUE_CLS[tone]}`}>
        {value}
        {unit && <span className="ml-1 text-base font-medium text-muted">{unit}</span>}
      </p>
      {hint && <p className="mt-1 text-xs text-faint">{hint}</p>}
    </div>
  );
}

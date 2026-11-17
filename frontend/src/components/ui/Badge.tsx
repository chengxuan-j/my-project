import type { ReactNode } from 'react';

type Tone = 'primary' | 'success' | 'danger' | 'warning' | 'neutral' | 'accent';

const TONE_CLS: Record<Tone, string> = {
  primary: 'bg-primary-soft text-primary',
  success: 'bg-success-soft text-success',
  danger: 'bg-danger-soft text-danger',
  warning: 'bg-warning-soft text-warning',
  accent: 'bg-accent-soft text-accent',
  neutral: 'bg-card-soft text-muted border border-hairline',
};

/** 行内状态标签：统一圆角胶囊、统一色调。 */
export function Badge({
  children,
  tone = 'neutral',
  className = '',
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-pill px-2.5 py-0.5 text-xs font-semibold leading-5 ${TONE_CLS[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

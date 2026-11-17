import type { ReactNode } from 'react';

interface Props {
  /** 小号眉题，如「吃药 · 复诊 · 血压」 */
  eyebrow?: string;
  title: ReactNode;
  description?: ReactNode;
  /** 右侧操作区 */
  actions?: ReactNode;
  /** 标题前的图标（传 lucide 组件） */
  icon?: ReactNode;
}

/**
 * 页面标题区：全站统一的信息层级入口。
 * eyebrow（眉题）→ title（页面标题）→ description（一句话说明）→ actions（主操作）。
 */
export function PageHeader({ eyebrow, title, description, actions, icon }: Props) {
  return (
    <header className="flex flex-wrap items-start justify-between gap-4 mb-6">
      <div className="min-w-0">
        {eyebrow && (
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            {eyebrow}
          </p>
        )}
        <h1 className="mt-1 flex items-center gap-2.5 text-3xl font-bold text-ink">
          {icon}
          <span className="min-w-0">{title}</span>
        </h1>
        {description && (
          <p className="mt-2 max-w-2xl text-base text-muted">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div>}
    </header>
  );
}

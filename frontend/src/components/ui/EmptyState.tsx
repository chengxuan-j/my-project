import type { ReactNode } from 'react';

/** 空状态：统一「图标 + 一句说明 + 可选操作」。 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className = '',
}: {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex flex-col items-center justify-center text-center py-12 px-6 ${className}`}>
      {icon && (
        <span className="flex h-14 w-14 items-center justify-center rounded-pill bg-primary-soft text-primary mb-4">
          {icon}
        </span>
      )}
      <p className="text-lg font-semibold text-ink">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

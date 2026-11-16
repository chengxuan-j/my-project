import type { ReactNode } from 'react';

interface Props {
  title?: ReactNode;
  /** 标题前图标（lucide 组件实例） */
  icon?: ReactNode;
  /** 标题行右侧：计数、状态、小操作 */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** 内容是否带默认内边距（表格/列表类可关掉） */
  padded?: boolean;
}

/**
 * 内容区块卡片：统一卡片头（图标 + 标题 + 右侧 meta/actions）与内容区。
 * 取代各页面手写的「白底 + 标题 + 内容」重复结构。
 */
export function SectionCard({
  title,
  icon,
  meta,
  actions,
  children,
  className = '',
  padded = true,
}: Props) {
  return (
    <section className={`bg-card rounded-card shadow-card border border-hairline ${className}`}>
      {(title || actions || meta) && (
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3 border-b border-hairline">
          <div className="flex items-center gap-2 min-w-0">
            {icon && <span className="text-primary shrink-0">{icon}</span>}
            {title && <h2 className="text-lg font-bold text-ink truncate">{title}</h2>}
            {meta && <span className="text-sm text-faint">{meta}</span>}
          </div>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={padded ? 'p-5' : ''}>{children}</div>
    </section>
  );
}

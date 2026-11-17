'use client';

/**
 * 根级错误边界：捕获 layout 及其子树的渲染异常。
 * 现场调试用 —— 直接把错误堆栈和 UA 显示在页面上，方便手机截图回报。
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const ua = typeof navigator !== 'undefined' ? navigator.userAgent : '(server)';
  const stack = (error?.stack || '').split('\n').slice(0, 8).join('\n');

  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          padding: 16,
          fontFamily: 'system-ui, -apple-system, sans-serif',
          background: '#fffdf7',
          color: '#1f2937',
        }}
      >
        <h1 style={{ fontSize: 18, color: '#b91c1c', margin: '0 0 8px' }}>页面出错了</h1>
        <p style={{ fontSize: 14, lineHeight: 1.6, margin: '0 0 12px' }}>
          请把下面这段完整截图发给开发者，就能定位问题。
        </p>
        <pre
          style={{
            fontSize: 12,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
            background: '#f3f4f6',
            padding: 12,
            borderRadius: 8,
            border: '1px solid #e5e7eb',
            margin: '0 0 16px',
            maxHeight: '60vh',
            overflow: 'auto',
          }}
        >
{`${error?.name || 'Error'}: ${error?.message || '(no message)'}
${error?.digest ? 'digest: ' + error.digest : ''}

${stack}

UA: ${ua}`}
        </pre>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            minHeight: 48,
            padding: '0 24px',
            fontSize: 16,
            fontWeight: 600,
            color: '#fff',
            background: '#f59e0b',
            border: 'none',
            borderRadius: 12,
          }}
        >
          重试
        </button>
      </body>
    </html>
  );
}

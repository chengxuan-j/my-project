'use client';

import { useEffect, useRef } from 'react';

export interface ServerEvent {
  type: string;
  [key: string]: unknown;
}

/** 订阅的后端事件类型 */
const EVENT_TYPES = ['family_message', 'family_message_read', 'family_digest', 'dog_relay'];

/**
 * SSE 基址：
 * - 默认直连后端（开发 / 局域网多设备），端口取 NEXT_PUBLIC_API_PORT，默认 8127；
 * - 上线同域部署时设 `NEXT_PUBLIC_SSE_BASE=''`，走同源（Nginx 反代）。
 *
 * 注意：SSE 不走 Next.js rewrites——rewrites 会缓冲响应，导致流拿不到。
 */
function resolveSseBase(): string {
  const cfg = process.env.NEXT_PUBLIC_SSE_BASE;
  if (cfg !== undefined) return cfg; // 空字符串表示同源
  if (typeof window !== 'undefined') {
    const port = process.env.NEXT_PUBLIC_API_PORT || '8127';
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return '';
}

/** 订阅后端 SSE 事件流（token 通过 query 传入，EventSource 无法自定义头）。 */
export function useServerEvents(
  token: string | null,
  onEvent: (e: ServerEvent) => void,
  enabled = true
) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    if (!enabled || !token || typeof window === 'undefined') return;
    const base = resolveSseBase();
    const es = new EventSource(
      `${base}/api/v1/events/stream?token=${encodeURIComponent(token)}`
    );

    const fns = EVENT_TYPES.map((type) => {
      const fn = (ev: MessageEvent) => {
        let data: Record<string, unknown> = {};
        try {
          data = JSON.parse(ev.data || '{}');
        } catch {
          // 忽略非 JSON 帧
        }
        handlerRef.current?.({ type, ...data });
      };
      es.addEventListener(type, fn as EventListener);
      return [type, fn] as const;
    });

    // EventSource 断线会自动重连，这里无需手动处理
    return () => {
      fns.forEach(([type, fn]) => es.removeEventListener(type, fn as EventListener));
      es.close();
    };
  }, [token, enabled]);
}

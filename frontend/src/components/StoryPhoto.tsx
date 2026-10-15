'use client';

import { useEffect, useRef, useState } from 'react';
import { ApiError, StoryMediaItem, apiBlobUrl } from '@/lib/api';

/**
 * 一张回忆照片。
 *
 * 照片接口是**鉴权**的（谁能看由服务端定：老人本人 / 已绑定家属 且 故事当前可见），
 * 而鉴权走 Authorization 头，`<img src>` 带不上——所以这里先 fetch 成 blob URL。
 * 组件卸载时必须 revoke，否则翻一遍回忆录就会攒下一堆不释放的图片。
 */
export function StoryPhoto({
  media,
  className = '',
  onClick,
}: {
  media: StoryMediaItem;
  className?: string;
  onClick?: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    apiBlobUrl(media.url)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u); // 组件已卸载，立刻释放
          return;
        }
        created = u;
        setUrl(u);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [media.url]);

  if (failed) {
    return (
      <div
        className={`flex flex-col items-center justify-center bg-warm-light text-gray-500 text-sm rounded-xl min-h-[84px] ${className}`}
      >
        <span aria-hidden>🖼️</span>
        <span>照片暂时看不到了</span>
      </div>
    );
  }
  if (!url) {
    return (
      <div
        className={`bg-warm-light animate-pulse rounded-xl min-h-[84px] ${className}`}
        aria-label="照片加载中"
      />
    );
  }
  return (
    /* eslint-disable-next-line @next/next/no-img-element */
    <img
      src={url}
      alt={media.caption || '回忆照片'}
      onClick={onClick}
      className={`rounded-xl object-cover ${onClick ? 'cursor-pointer' : ''} ${className}`}
    />
  );
}

/** 挂在一条回忆下面的照片条（老人与家属共用）。 */
export function StoryPhotoStrip({
  media,
  onDelete,
  onOpen,
  compact = false,
}: {
  media: StoryMediaItem[];
  /** 传了才出现删除按钮；权限由调用方决定 */
  onDelete?: (m: StoryMediaItem) => void;
  onOpen?: (m: StoryMediaItem) => void;
  compact?: boolean;
}) {
  if (media.length === 0) return null;
  const size = compact ? 'w-24 h-24' : 'w-32 h-32';

  return (
    <ul className="flex flex-wrap gap-3 mt-3">
      {media.map((m) => (
        <li key={m.id} className="relative">
          <StoryPhoto
            media={m}
            className={`${size} border border-amber-200`}
            onClick={onOpen ? () => onOpen(m) : undefined}
          />
          {m.caption && (
            <p className="text-sm text-gray-600 mt-1 max-w-[8rem] truncate" title={m.caption}>
              {m.caption}
            </p>
          )}
          {!m.caption && m.uploaded_by_role === 'family' && (
            <p className="text-sm text-gray-400 mt-1">家人补的</p>
          )}
          {onDelete && (
            <button
              type="button"
              onClick={() => onDelete(m)}
              aria-label={`删除照片${m.caption ? `：${m.caption}` : ''}`}
              className="absolute -top-2 -right-2 min-h-[32px] min-w-[32px] rounded-full bg-white border-2 border-red-300 text-red-600 text-lg leading-none"
            >
              ×
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * 照片上传：选文件 → 填一句说明（可空）→ 上传。
 *
 * 不做本地预览（预览要再造一个 blob 生命周期，而上传通常一两秒就回来了）；
 * 上传成功后由父组件刷新列表，用真实结果说话更不容易对不上。
 */
export function StoryPhotoUploader({
  storyTitle,
  onUpload,
  onCancel,
}: {
  storyTitle?: string;
  onUpload: (file: File, caption: string) => Promise<void>;
  onCancel?: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [caption, setCaption] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);

  const reset = () => {
    setFile(null);
    setCaption('');
    setError('');
    if (inputRef.current) inputRef.current.value = '';
  };

  const submit = async () => {
    if (!file) {
      setError('先选一张照片吧');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await onUpload(file, caption.trim());
      reset();
      onCancel?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '上传失败，请再试一次');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-3 rounded-2xl border-2 border-warm-light bg-warm-bg p-4 space-y-3">
      <p className="font-medium text-gray-800">
        给{storyTitle ? `「${storyTitle}」` : '这段回忆'}补一张照片
      </p>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,image/bmp,image/tiff"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="block w-full text-base text-gray-700"
        aria-label="选择照片"
      />
      <input
        type="text"
        value={caption}
        onChange={(e) => setCaption(e.target.value)}
        maxLength={60}
        placeholder="写一句话说明（可留空）"
        className="w-full min-h-[48px] px-3 rounded-xl border-2 border-warm-light focus:border-warm-primary outline-none bg-white"
      />
      {error && (
        <p className="text-red-600 bg-red-50 border border-red-200 rounded-xl px-3 py-2">
          {error}
        </p>
      )}
      <div className="flex gap-2 flex-wrap">
        <button
          type="button"
          onClick={submit}
          disabled={busy || !file}
          className="min-h-[48px] px-5 rounded-xl bg-warm-primary hover:bg-warm-dark disabled:opacity-50 text-white font-medium"
        >
          {busy ? '上传中…' : '上传照片'}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={() => {
              reset();
              onCancel();
            }}
            disabled={busy}
            className="min-h-[48px] px-5 rounded-xl bg-white border-2 border-warm-light text-gray-700"
          >
            取消
          </button>
        )}
      </div>
      <p className="text-sm text-gray-500">
        最多 5MB，支持 jpg / png / webp 等常见格式。照片只是补在这段回忆旁边，
        不会改动老人讲过的内容。
      </p>
    </div>
  );
}

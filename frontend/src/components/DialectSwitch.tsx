'use client';

import { useEffect, useState } from 'react';
import { ApiError, DialectState, settingsApi } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

/** 后端没连上时的兜底列表，保证弹窗永远可点。 */
const FALLBACK_OPTIONS = ['普通话', '四川话', '东北话', '粤语', '上海话', '河南话', '陕西话'];

/**
 * 方言模式开关。
 *
 * 用居中弹层而不是下拉菜单：导航栏是 sticky + flex-wrap，下拉层在窄屏
 * 或层级变化时容易被裁掉/点不到。改成 fixed 全屏遮罩后，和视口、导航栏
 * 高度都无关，老人点起来也更大更好点。
 *
 * 状态存服务端：方言要影响后端拼 prompt，只存浏览器换设备就对不上。
 */
export function DialectSwitch() {
  const { accessToken, user } = useAuthStore();
  const [state, setState] = useState<DialectState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!accessToken || user?.role !== 'elderly') return;
    settingsApi
      .dialect()
      .then(setState)
      .catch(() => setState(null));
  }, [accessToken, user?.role]);

  // 家属没有方言设置
  if (!user || user.role !== 'elderly') return null;

  const options = state?.options?.map((o) => o.name) ?? FALLBACK_OPTIONS;
  const activeName = state?.enabled ? state.active_dialect : '普通话';

  const choose = async (name: string) => {
    if (busy) return;
    setBusy(name);
    setError('');
    try {
      const next = await settingsApi.setDialect(name !== '普通话', name);
      setState(next);
      setOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '保存失败，请再试一次');
    } finally {
      setBusy('');
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setError('');
          setOpen(true);
        }}
        aria-haspopup="dialog"
        title="让 AI 用方言和你聊天"
        className={`min-h-[48px] px-3 rounded-btn text-base flex items-center gap-1 ${
          state?.enabled
            ? 'bg-primary text-on-primary font-bold shadow-btn'
            : 'bg-primary-soft text-primary hover:bg-primary-softer font-bold'
        }`}
      >
        {state?.enabled ? state.active_dialect : '方言'}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[80] bg-black/50 flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="选择方言"
            className="w-full max-w-md bg-card rounded-card shadow-float overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-card px-5 py-4 flex items-center justify-between border-b border-hairline">
              <div>
                <p className="text-xl font-bold text-ink">选一种方言</p>
                <p className="text-sm text-muted mt-0.5">
                  选好之后，AI 回你的话就用这种口语
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="min-h-[44px] min-w-[44px] rounded-btn hover:bg-primary-soft text-xl text-muted"
                aria-label="关闭"
              >
                ✕
              </button>
            </div>

            <ul className="p-4 space-y-2 max-h-[55vh] overflow-y-auto">
              {options.map((name) => {
                const active = name === activeName;
                const isOff = name === '普通话';
                return (
                  <li key={name}>
                    <button
                      type="button"
                      onClick={() => choose(name)}
                      disabled={!!busy}
                      aria-pressed={active}
                      className={`w-full min-h-[56px] px-4 rounded-btn border text-lg flex items-center justify-between ${
                        active
                          ? 'border-hairline-strong bg-primary-soft text-primary font-bold'
                          : 'border-hairline bg-card text-ink hover:bg-primary-softer'
                      }`}
                    >
                      <span>
                        {name}
                        {isOff && (
                          <span className="ml-2 text-sm font-normal text-muted">
                            不用方言
                          </span>
                        )}
                      </span>
                      {busy === name ? (
                        <span className="text-sm text-muted">保存中…</span>
                      ) : (
                        active && <span aria-hidden>✓</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>

            {error && (
              <p className="px-5 pb-2 text-danger text-sm text-center">{error}</p>
            )}

            <div className="px-5 pb-5">
              <p className="text-sm text-muted leading-relaxed">
                选好方言后：说话按方言识别（四川话、粤语、上海话等），
                回复也用方言腔念出来。口音特别重时可以说慢一点。
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

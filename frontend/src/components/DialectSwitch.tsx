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
        className={`min-h-[48px] px-3 rounded-lg text-base ${
          state?.enabled
            ? 'bg-white text-warm-primary font-bold'
            : 'bg-warm-dark hover:bg-amber-700'
        }`}
      >
        {state?.enabled ? `🗣 ${state.active_dialect}` : '🗣 方言'}
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
            className="w-full max-w-md bg-white rounded-3xl shadow-2xl border-2 border-warm-light overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="bg-warm-primary text-white px-5 py-4 flex items-center justify-between">
              <div>
                <p className="text-xl font-bold">🗣 选一种方言</p>
                <p className="text-sm text-amber-50 mt-0.5">
                  选好之后，AI 回你的话就用这种口语
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="min-h-[44px] min-w-[44px] rounded-lg hover:bg-warm-dark text-xl"
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
                      className={`w-full min-h-[56px] px-4 rounded-xl border-2 text-lg flex items-center justify-between ${
                        active
                          ? 'border-warm-primary bg-warm-light text-warm-dark font-bold'
                          : 'border-warm-light bg-white text-gray-800 hover:bg-warm-light/60'
                      }`}
                    >
                      <span>
                        {name}
                        {isOff && (
                          <span className="ml-2 text-sm font-normal text-gray-500">
                            不用方言
                          </span>
                        )}
                      </span>
                      {busy === name ? (
                        <span className="text-sm text-gray-500">保存中…</span>
                      ) : (
                        active && <span aria-hidden>✓</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>

            {error && (
              <p className="px-5 pb-2 text-rose-600 text-sm text-center">{error}</p>
            )}

            <div className="px-5 pb-5">
              <p className="text-sm text-gray-500 leading-relaxed">
                打字时用方言词，AI 能看懂；说话时语音识别按普通话模型走，
                口音太重可能识别不准，重要的事建议打字或说慢一点。
              </p>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

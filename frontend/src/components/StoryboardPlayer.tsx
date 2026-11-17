'use client';

import { useEffect, useRef, useState } from 'react';
import { CompilationItem, speechApi } from '@/lib/api';

/** 一段镜头的占位色块：按情绪基调给色调，代替画面（契约6：不生成画面）。 */
const TONE_TINTS: Record<string, string> = {
  温暖: 'bg-butter',
  自豪: 'bg-warning-soft',
  辛酸: 'bg-lilac-soft',
  平淡: 'bg-card-soft',
  创伤: 'bg-primary-soft',
  怀念: 'bg-accent-soft',
};

function Placeholder({ tone, label }: { tone: string; label: string }) {
  const tint = TONE_TINTS[tone] || TONE_TINTS['平淡'];
  return (
    <div
      className={`w-full aspect-video rounded-card ${tint} flex flex-col items-center justify-center text-ink text-center p-6`}
    >
      <span className="text-lg font-bold">{label}</span>
      <span className="text-sm opacity-80 mt-2">
        （画面示意占位，系统不生成影像）
      </span>
    </div>
  );
}

/**
 * 故事板播放器：逐条高亮 + TTS 念旁白。
 *
 * 这里**没有**「下载视频」「重新生成画面」这类按钮——契约6 明确止于提示词。
 * 底部折叠里给的是完整提示词，家属可以复制到任意视频工具自己做，
 * 这一步发生在系统之外，系统不参与也不承诺效果。
 */
export function StoryboardPlayer({ compilation }: { compilation: CompilationItem }) {
  const pkg = compilation.prompt_package;
  const scenes = pkg?.scenes ?? [];
  const [active, setActive] = useState(0);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 播放：合成当前段旁白 → 播完自动跳下一段
  useEffect(() => {
    if (!playing || scenes.length === 0) return;
    let cancelled = false;

    const run = async () => {
      const scene = scenes[active];
      let waited = false;
      try {
        const res = await speechApi.tts(scene.narration);
        if (cancelled) return;
        if (res.audio_url && audioRef.current) {
          audioRef.current.src = res.audio_url;
          waited = true;
          await audioRef.current.play().catch(() => {});
        }
      } catch {
        // TTS 不可用就按时长静默走过这一段，不打断播放节奏
      }
      if (cancelled) return;
      if (!waited) {
        await new Promise((r) => {
          timerRef.current = setTimeout(r, scene.duration_seconds * 1000);
        });
      }
    };

    run();
    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      audioRef.current?.pause();
    };
  }, [playing, active, scenes]);

  const handleEnded = () => {
    if (active + 1 < scenes.length) setActive(active + 1);
    else setPlaying(false);
  };

  if (!pkg || scenes.length === 0) {
    return (
      <div className="rounded-card border border-hairline bg-card p-6 text-muted hc-invert">
        这段短片还没有可用的故事板。
      </div>
    );
  }

  const current = scenes[active];

  return (
    <div className="space-y-4">
      <audio ref={audioRef} onEnded={handleEnded} className="hidden" />

      <div className="flex items-center justify-between flex-wrap gap-3">
        <h2 className="text-xl font-bold text-ink">{pkg.title}</h2>
        <div className="flex items-center gap-3">
          <span className="text-muted">
            共 {scenes.length} 段 · 约 {pkg.total_seconds} 秒
          </span>
          <button
            onClick={() => setPlaying((v) => !v)}
            className="min-h-[48px] px-5 rounded-btn bg-primary hover:bg-primary-strong text-on-primary font-bold"
          >
            {playing ? '⏸ 暂停' : '▶ 播放'}
          </button>
        </div>
      </div>

      <Placeholder
        tone={current.emotion_tone}
        label={`第 ${current.index} 段｜${current.display_time || current.era || '时间不详'}｜${current.duration_seconds} 秒`}
      />

      <div className="rounded-card border border-hairline bg-card p-5 hc-invert">
        <div className="flex items-center gap-3 flex-wrap mb-2">
          <h3 className="text-lg font-bold text-ink">{current.title || '一段往事'}</h3>
          {current.era && (
            <span className="text-sm bg-primary-soft text-primary rounded-lg px-2 py-0.5">
              {current.era}
            </span>
          )}
          {current.narration_source === 'original' && (
            <span className="text-sm border border-hairline text-primary rounded-lg px-2 py-0.5">
              旁白是老人原话
            </span>
          )}
        </div>
        <p className="text-xl leading-relaxed text-ink">{current.narration}</p>

        <details className="mt-3">
          <summary className="cursor-pointer text-muted min-h-[40px] flex items-center">
            看这段的画面提示词
          </summary>
          <p className="mt-2 text-base text-muted bg-canvas rounded-btn p-3">
            {current.visual_prompt}
          </p>
          <p className="mt-2 text-sm text-muted">
            出处（老人原话）：{current.source_evidence}
          </p>
        </details>
      </div>

      {pkg.disclaimer && (
        <p className="text-sm text-muted leading-relaxed">{pkg.disclaimer}</p>
      )}
    </div>
  );
}

/** 把整包提示词拼成纯文本：粘到外部视频工具里就能用。 */
export function promptPackageToText(compilation: CompilationItem): string {
  const pkg = compilation.prompt_package;
  if (!pkg) return '';
  return [
    `# ${pkg.title}`,
    `视角：${pkg.perspective === 'first_person' ? '第一人称' : '第三人称'}`,
    `总时长：约 ${pkg.total_seconds} 秒`,
    '',
    ...pkg.scenes.map((s) =>
      [
        `## 第 ${s.index} 段（${s.display_time || '时间不详'}｜${s.duration_seconds} 秒）`,
        `旁白：${s.narration}`,
        `画面：${s.visual_prompt}`,
        `出处：${s.source_evidence}`,
      ].join('\n')
    ),
    '',
    pkg.disclaimer,
  ].join('\n');
}

/**
 * 「复制全部提示词」。老人端与家属端共用一份实现——
 * 两边都只是把同一包文字交出去，多写一份就会有两处漂移。
 */
export function PromptCopyButton({ compilation }: { compilation: CompilationItem }) {
  const [copied, setCopied] = useState(false);
  if (!compilation.prompt_package) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(promptPackageToText(compilation));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="min-h-[48px] px-4 rounded-btn bg-card border border-primary text-primary font-medium hover:bg-primary-soft"
    >
      {copied ? '✅ 已复制' : '📋 复制全部提示词'}
    </button>
  );
}

/** 段落总览 + 完整提示词（折叠），供家属复制到外部视频工具。 */
export function StoryboardSceneList({ compilation }: { compilation: CompilationItem }) {
  const pkg = compilation.prompt_package;
  if (!pkg) return null;
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-bold text-ink">故事板</h3>
      <ol className="space-y-3">
        {pkg.scenes.map((s) => (
          <li key={s.index} className="rounded-card border border-hairline bg-card p-4 hc-invert">
            <div className="flex items-baseline justify-between flex-wrap gap-2">
              <strong className="text-ink">
                {s.index}. {s.title || '一段往事'}
              </strong>
              <span className="text-sm text-muted">
                {s.display_time || '时间不详'} · {s.duration_seconds} 秒
                {s.narration_source === 'original' && ' · 原话'}
              </span>
            </div>
            <p className="mt-2 text-lg text-ink">{s.narration}</p>
            <p className="mt-2 text-base text-muted">{s.visual_prompt}</p>
          </li>
        ))}
      </ol>

      {pkg.llm_used === false && (
        <p className="text-sm text-muted">
          这次是离线整理的（没能连上模型），旁白直接用老人原话，画面提示为占位。
        </p>
      )}
    </section>
  );
}

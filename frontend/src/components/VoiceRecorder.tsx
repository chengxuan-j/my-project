'use client';

import { useRef, useState } from 'react';
import { chatApi, speechApi } from '@/lib/api';

interface Props {
  onRecognized: (text: string) => void;
  onError?: (msg: string) => void;
  /** 停止录音的瞬间触发（早于识别完成）——用于"接话"即时出声 */
  onStopRecording?: () => void;
}

/**
 * 大圆形🎤按钮：点击开始录音 → 再次点击结束录音 → 上传 → 轮询识别结果
 *
 * 录音期间会周期性把"到目前为止的音频"送去识别，拿到部分文本后调用
 * /chat/speculate 让后端**提前把回复算起来**（"边说边算"）。
 * 老人停下时若最终文本与预生成文本一致，回复几乎立刻出来。
 */
export function VoiceRecorder({ onRecognized, onError, onStopRecording }: Props) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  // 预生成相关：避免并发提交、记录上次已预生成的文本
  const specBusyRef = useRef(false);
  const lastSpecRef = useRef('');
  const specTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /** 用"目前累计的音频"取一次部分识别结果，并触发预生成 */
  const runSpeculation = async () => {
    if (specBusyRef.current || chunksRef.current.length === 0) return;
    specBusyRef.current = true;
    try {
      const mime = mediaRecorderRef.current?.mimeType || 'audio/webm';
      const blob = new Blob(chunksRef.current, { type: mime });
      const { task_id } = await speechApi.asrSubmit(blob);
      // 部分识别只等很短时间：拿不到就放弃，不能拖累正式流程
      let text = '';
      for (let i = 0; i < 4; i++) {
        await new Promise((r) => setTimeout(r, 400));
        const res = await speechApi.asrResult(task_id);
        if (res.text) {
          text = res.text;
          break;
        }
        if (res.status === 'failed' || res.status === 'error') break;
      }
      const trimmed = text.trim();
      if (trimmed.length >= 6 && trimmed !== lastSpecRef.current) {
        lastSpecRef.current = trimmed;
        chatApi.speculate(trimmed).catch(() => {
          // 预生成失败无所谓，正式链路照常
        });
      }
    } catch {
      // 部分识别失败静默，不影响正常录音
    } finally {
      specBusyRef.current = false;
    }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      lastSpecRef.current = '';
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        if (specTimerRef.current) clearInterval(specTimerRef.current);
        specTimerRef.current = null;
        stream.getTracks().forEach((t) => t.stop());
        // 话音一落就通知外部（接话短句此时出声，不用等 ASR 那 1.5 秒）
        onStopRecording?.();
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        await handleUpload(blob);
      };
      mediaRecorderRef.current = mr;
      // 每 1 秒切一片，这样录音过程中就能拿到"部分音频"做预生成
      mr.start(1000);
      // 每 2 秒尝试一次部分识别 + 预生成
      specTimerRef.current = setInterval(() => {
        void runSpeculation();
      }, 2000);
      setRecording(true);
    } catch (err) {
      onError?.('无法访问麦克风，请检查浏览器权限');
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && recording) {
      mediaRecorderRef.current.stop();
      setRecording(false);
    }
  };

  const handleUpload = async (blob: Blob) => {
    setProcessing(true);
    try {
      const { task_id } = await speechApi.asrSubmit(blob);
      // 轮询识别结果
      const text = await pollResult(task_id);
      if (text) {
        onRecognized(text);
      } else {
        onError?.('没有听清，请再说一次');
      }
    } catch (err) {
      onError?.(err instanceof Error ? err.message : '语音识别失败');
    } finally {
      setProcessing(false);
    }
  };

  const pollResult = async (taskId: string, maxTries = 25): Promise<string | null> => {
    // 首次立即查询（此前循环开头先白等 1 秒，结果早就绪也要多等 1s），
    // 之后 300ms 起、逐步放宽到 1s：降低首字延迟，又不至于密集轮询后端。
    for (let i = 0; i < maxTries; i++) {
      const res = await speechApi.asrResult(taskId);
      if (res.status === 'done' || res.status === 'success' || res.text) {
        return res.text || null;
      }
      if (res.status === 'failed' || res.status === 'error') {
        throw new Error(res.error || '识别失败');
      }
      await new Promise((r) => setTimeout(r, Math.min(300 * (i + 1), 1000)));
    }
    throw new Error('识别超时');
  };

  const cls = recording
    ? 'bg-red-500 scale-110 animate-pulse'
    : processing
      ? 'bg-gray-400'
      : 'bg-warm-primary hover:bg-warm-dark';

  const toggleRecording = () => {
    if (processing) return;
    if (recording) {
      stopRecording();
    } else {
      startRecording();
    }
  };

  return (
    <button
      type="button"
      disabled={processing}
      onClick={toggleRecording}
      className={`w-20 h-20 rounded-full text-white text-3xl shadow-lg transition-all flex items-center justify-center select-none touch-none ${cls}`}
      title={recording ? '点击结束录音' : '点击开始录音'}
      aria-label={recording ? '录音中，点击结束' : '点击开始录音'}
    >
      {processing ? '⏳' : recording ? '🔴' : '🎤'}
    </button>
  );
}

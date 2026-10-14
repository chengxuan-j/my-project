'use client';

import { useRef, useState } from 'react';
import { speechApi } from '@/lib/api';

interface Props {
  onRecognized: (text: string) => void;
  onError?: (msg: string) => void;
}

/**
 * 大圆形🎤按钮：点击开始录音 → 再次点击结束录音 → 上传 → 轮询识别结果
 */
export function VoiceRecorder({ onRecognized, onError }: Props) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: mr.mimeType || 'audio/webm' });
        await handleUpload(blob);
      };
      mediaRecorderRef.current = mr;
      mr.start();
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

  const pollResult = async (taskId: string, maxTries = 20): Promise<string | null> => {
    for (let i = 0; i < maxTries; i++) {
      await new Promise((r) => setTimeout(r, 1000));
      const res = await speechApi.asrResult(taskId);
      if (res.status === 'done' || res.status === 'success' || res.text) {
        return res.text || null;
      }
      if (res.status === 'failed' || res.status === 'error') {
        throw new Error(res.error || '识别失败');
      }
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

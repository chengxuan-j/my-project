'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { VisionEngine, Action, CHEATSHEET } from '@/lib/visionEngine';
import { dogApi, speechApi } from '@/lib/api';

interface CameraPanelProps {
  onClose: () => void;
  /** 语音识别为非动作指令时，把文字交给父组件（如发到聊天） */
  onVoice?: (text: string) => void;
}

/** 语音关键词 → 狗动作 key（必须和后端 dog_control.KEY_MAP 一致） */
const VOICE_ACTION_MAP: Record<string, string> = {
  前进: 'walk_forward', 往前走: 'walk_forward', 走: 'walk_forward',
  后退: 'walk_back', 往后退: 'walk_back', 退: 'walk_back',
  左转: 'turn_left', 往左转: 'turn_left',
  右转: 'turn_right', 往右转: 'turn_right',
  停止: 'stop', 停: 'stop', 别动: 'stop',
  握手: 'stand', 握个手: 'stand',
  摇摆: 'shake', 摇一摇: 'shake', 摇尾巴: 'shake',
  鞠躬: 'sit', 弯腰: 'sit',
  伸懒腰: 'stretch',
};

const ACTION_LABEL: Record<string, string> = {
  walk_forward: '前进', walk_back: '后退', turn_left: '左转', turn_right: '右转',
  stop: '停止', sit: '鞠躬', stand: '握手', stretch: '伸懒腰', shake: '摇摆',
};

export function CameraPanel({ onClose, onVoice }: CameraPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<VisionEngine | null>(null);

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [cameraError, setCameraError] = useState('');

  const [status, setStatus] = useState({
    currentAction: null as string | null,
    progress: 0,
    awaitingRelease: false,
    cooldownLeft: 0,
  });

  const [lastDogAction, setLastDogAction] = useState<{
    label: string;
    reached: boolean;
    ts: number;
  } | null>(null);

  const [ttsSpeaking, setTtsSpeaking] = useState(false);

  // 语音控制状态
  const [recording, setRecording] = useState(false);
  const [voiceProcessing, setVoiceProcessing] = useState(false);
  const [voiceHint, setVoiceHint] = useState(''); // 显示最近语音状态/结果
  const [recordingSec, setRecordingSec] = useState(0);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const voiceChunksRef = useRef<Blob[]>([]);
  const voiceTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const voiceAutoStopRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 启动摄像头
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    let stream: MediaStream | null = null;

    const startCamera = async () => {
      try {
        // 优先前置摄像头；台式机外接摄像头常不支持 facingMode，失败则回退到任意摄像头
        const attempts = [
          { video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false },
          { video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false },
        ];
        for (const c of attempts) {
          try {
            stream = await navigator.mediaDevices.getUserMedia(c);
            break;
          } catch {
            // 尝试下一组约束
          }
        }
        if (!stream) {
          throw new Error('no camera available');
        }
        video.srcObject = stream;
        await video.play();
      } catch (err) {
        setCameraError(
          err instanceof Error
            ? err.name === 'NotAllowedError'
              ? '摄像头权限被拒绝，请在浏览器地址栏允许访问摄像头'
              : `摄像头启动失败：${err.message}`
            : '摄像头启动失败'
        );
        setLoading(false);
      }
    };

    startCamera();
    return () => {
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  // 初始化 MediaPipe 并启动引擎
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || cameraError) return;

    let mounted = true;

    const init = async () => {
      try {
        const engine = new VisionEngine({
          onAction: async (action: Action) => {
            if (!mounted) return;
            // 发送指令给机器狗
            try {
              const res = await dogApi.action(action.key);
              if (mounted) {
                setLastDogAction({
                  label: res.action_name,
                  reached: res.dog_reached,
                  ts: Date.now(),
                });
                // TTS 播报
                if (!ttsSpeaking && res.dog_reached) {
                  setTtsSpeaking(true);
                  try {
                    const tts = await speechApi.tts(
                      `小狗为您表演${res.action_name}`
                    );
                    const audio = new Audio(tts.audio_url);
                    audio.onended = () => setTtsSpeaking(false);
                    audio.onerror = () => setTtsSpeaking(false);
                    await audio.play();
                  } catch {
                    setTtsSpeaking(false);
                  }
                }
              }
            } catch (e) {
              // 静默失败，UI 继续工作
            }
          },
          onStatus: (s) => {
            if (mounted) {
              setStatus(s);
            }
          },
        });
        await engine.init();
        if (!mounted) {
          engine.stop();
          return;
        }
        engineRef.current = engine;
        engine.start(video, canvas);
        setLoading(false);
      } catch (err) {
        if (mounted) {
          setLoadError(
            err instanceof Error
              ? `视觉引擎加载失败：${err.message}`
              : '视觉引擎加载失败，请检查网络后重试'
          );
          setLoading(false);
        }
      }
    };

    // 等摄像头 ready 后再初始化引擎
    const waitAndInit = () => {
      if (video.readyState >= 2) {
        init();
      } else {
        video.addEventListener('loadeddata', init, { once: true });
      }
    };
    waitAndInit();

    return () => {
      mounted = false;
      engineRef.current?.stop();
      engineRef.current = null;
    };
  }, [cameraError, ttsSpeaking]);

  const handleClose = useCallback(() => {
    engineRef.current?.stop();
    engineRef.current = null;
    const video = videoRef.current;
    if (video?.srcObject) {
      (video.srcObject as MediaStream).getTracks().forEach((t) => t.stop());
    }
    onClose();
  }, [onClose]);

  // ---------- 语音控制（点击切换：开始/停止） ----------
  const toggleRecording = async () => {
    if (recording) {
      // 停止录音
      if (mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
      }
      if (voiceTimerRef.current) clearInterval(voiceTimerRef.current);
      if (voiceAutoStopRef.current) clearTimeout(voiceAutoStopRef.current);
      setRecording(false);
      setRecordingSec(0);
      setVoiceHint('⏳ 正在识别…');
      return;
    }
    // 开始录音
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      voiceChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) voiceChunksRef.current.push(e.data);
      };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(voiceChunksRef.current, { type: mr.mimeType || 'audio/webm' });
        await handleVoiceUpload(blob);
      };
      mediaRecorderRef.current = mr;
      mr.start();
      setRecording(true);
      setRecordingSec(0);
      setVoiceHint('🎤 正在听您说… 再点一下结束');
      // 计时器
      voiceTimerRef.current = setInterval(() => {
        setRecordingSec((s) => s + 1);
      }, 1000);
      // 10 秒自动停止
      voiceAutoStopRef.current = setTimeout(() => {
        if (mediaRecorderRef.current) mediaRecorderRef.current.stop();
        if (voiceTimerRef.current) clearInterval(voiceTimerRef.current);
        setRecording(false);
        setRecordingSec(0);
        setVoiceHint('⏳ 正在识别…');
      }, 10000);
    } catch {
      setVoiceHint('⚠️ 无法使用麦克风');
    }
  };

  const handleVoiceUpload = async (blob: Blob) => {
    setVoiceProcessing(true);
    try {
      const { task_id } = await speechApi.asrSubmit(blob);
      const text = await pollVoiceResult(task_id);
      if (text) {
        await handleVoiceText(text);
      } else {
        setVoiceHint('🤔 没听清，请再说一次');
      }
    } catch {
      setVoiceHint('❌ 语音识别失败');
    } finally {
      setVoiceProcessing(false);
    }
  };

  /** 轮询间隔 0.5s（提速） */
  const pollVoiceResult = async (taskId: string, maxTries = 40): Promise<string | null> => {
    for (let i = 0; i < maxTries; i++) {
      await new Promise((r) => setTimeout(r, 500));
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

  const handleVoiceText = async (text: string) => {
    // 1) 尝试匹配狗动作关键词
    for (const [keyword, key] of Object.entries(VOICE_ACTION_MAP)) {
      if (text.includes(keyword)) {
        setVoiceHint(`🐶 语音指令：${ACTION_LABEL[key] ?? key}`);
        try {
          const res = await dogApi.action(key);
          setLastDogAction({ label: ACTION_LABEL[key] ?? key, reached: res.dog_reached, ts: Date.now() });
          if (res.dog_reached) {
            // TTS 播报
            const msg = `小狗收到，为您表演${ACTION_LABEL[key]}`;
            const tts = await speechApi.tts(msg);
            if (tts.audio_url) {
              const audio = new Audio(tts.audio_url);
              audio.play().catch(() => {});
            }
          }
        } catch {
          setVoiceHint('🐶 小狗离线，指令未送达');
        }
        return;
      }
    }
    // 2) 不是动作指令 → 交给父组件处理（如普通聊天）
    setVoiceHint(`💬 你说：${text}`);
    onVoice?.(text);
  };

  // HUD 颜色
  const progressColor = status.awaitingRelease
    ? '#F59E0B'
    : status.progress >= 1
    ? '#10B981'
    : '#3B82F6';

  const statusText = status.awaitingRelease
    ? '姿势已触发 · 请放下手回到中立位'
    : status.cooldownLeft > 0
    ? `冷却中 ${status.cooldownLeft.toFixed(1)}s`
    : '就绪 · 对着摄像头做动作';

  return (
    <div className="fixed inset-0 z-50 bg-black flex flex-col">
      {/* 顶部栏 */}
      <div className="flex items-center justify-between px-4 py-3 bg-black/60">
        <h2 className="text-white text-2xl font-bold">🎥 动作指挥小狗</h2>
        <button
          onClick={handleClose}
          className="w-12 h-12 rounded-full bg-white/20 text-white text-2xl font-bold hover:bg-white/30"
        >
          ✕
        </button>
      </div>

      {/* 视频区 */}
      <div className="relative flex-1 flex items-center justify-center overflow-hidden">
        <video
          ref={videoRef}
          className="absolute inset-0 w-full h-full object-cover opacity-0"
          playsInline
          muted
        />
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full object-cover"
        />

        {/* 加载遮罩 */}
        {(loading || loadError || cameraError) && (
          <div className="absolute inset-0 bg-black/80 flex flex-col items-center justify-center text-white px-6 text-center">
            {loading && !loadError && !cameraError && (
              <>
                <div className="w-16 h-16 border-4 border-white/30 border-t-white rounded-full animate-spin mb-4" />
                <p className="text-xl font-bold">正在启动视觉引擎…</p>
                <p className="text-sm text-white/60 mt-2">首次加载需要 10~30 秒下载模型</p>
              </>
            )}
            {(loadError || cameraError) && (
              <>
                <p className="text-4xl mb-3">⚠️</p>
                <p className="text-xl font-bold text-red-300 mb-2">
                  {loadError || cameraError}
                </p>
                <button
                  onClick={handleClose}
                  className="mt-4 px-6 py-3 rounded-xl bg-white text-black text-lg font-bold"
                >
                  返回
                </button>
              </>
            )}
          </div>
        )}

        {/* HUD 叠加层 */}
        {!loading && !loadError && !cameraError && (
          <>
            {/* 左上角：当前姿势 + 进度条 */}
            <div className="absolute top-4 left-4 bg-black/50 rounded-xl px-4 py-3 text-white min-w-[220px]">
              <p className="text-lg font-bold">
                {status.currentAction ?? '中立位'}
              </p>
              <div className="w-full h-3 bg-white/20 rounded-full mt-2 overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.round(status.progress * 100)}%`,
                    backgroundColor: progressColor,
                  }}
                />
              </div>
              <p className="text-sm mt-1 text-white/80">{statusText}</p>
            </div>

            {/* 右上角：最近动作 */}
            {lastDogAction && Date.now() - lastDogAction.ts < 5000 && (
              <div
                className={`absolute top-4 right-4 rounded-xl px-4 py-3 text-white text-lg font-bold ${
                  lastDogAction.reached ? 'bg-green-600/80' : 'bg-red-600/80'
                }`}
              >
                {lastDogAction.reached
                  ? `🐶 小狗执行：${lastDogAction.label}`
                  : `🐶 小狗离线 · 未执行${lastDogAction.label}`}
              </div>
            )}

            {/* 右下角：FPS/状态 */}
            <div className="absolute bottom-4 right-4 bg-black/40 rounded-lg px-3 py-1 text-white/60 text-sm">
              {voiceHint || (ttsSpeaking ? '🔊 播报中…' : '视觉引擎运行中')}
            </div>
          </>
        )}
      </div>

      {/* 底部：语音控制 */}
      {!loading && !loadError && !cameraError && (
        <div className="bg-neutral-800 px-4 py-3 flex flex-col items-center gap-2">
          <div className="flex items-center gap-3">
            {/* 录音波形动画 */}
            {recording && (
              <div className="flex items-end gap-[3px] h-8">
                {[0, 1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className="w-[4px] bg-red-400 rounded-full animate-bounce"
                    style={{
                      height: '100%',
                      animationDelay: `${i * 0.12}s`,
                      animationDuration: '0.6s',
                    }}
                  />
                ))}
              </div>
            )}
            <button
              type="button"
              disabled={voiceProcessing}
              onClick={toggleRecording}
              className={`w-16 h-16 rounded-full text-white text-2xl shadow-lg transition-all flex items-center justify-center select-none ${
                recording
                  ? 'bg-red-500 scale-110'
                  : voiceProcessing
                    ? 'bg-gray-400'
                    : 'bg-warm-primary hover:bg-warm-dark hover:scale-105'
              }`}
              title={recording ? '点一下结束录音' : '点一下开始说话'}
            >
              {voiceProcessing ? '⏳' : recording ? '⏹' : '🎤'}
            </button>
            {recording && (
              <span className="text-red-400 text-lg font-bold tabular-nums">
                {recordingSec}s
              </span>
            )}
          </div>
          <p className="text-white/60 text-sm">
            {recording
              ? '正在录音… 再点一下结束（最长10秒）'
              : voiceProcessing
                ? '正在识别您说的话…'
                : '点麦克风说话，小狗也能听懂'}
          </p>
        </div>
      )}

      {/* 底部：姿势速查表 */}
      {!loading && !loadError && !cameraError && (
        <div className="bg-neutral-900 px-4 py-3">
          <p className="text-white/60 text-sm mb-2 text-center">对着摄像头做这些动作，小狗就会回应您</p>
          <div className="flex flex-wrap justify-center gap-2">
            {CHEATSHEET.map((a) => (
              <div
                key={a.key}
                className={`px-3 py-2 rounded-lg text-center min-w-[90px] ${
                  status.currentAction === a.label
                    ? 'bg-green-600 text-white'
                    : 'bg-white/10 text-white/80'
                }`}
              >
                <p className="text-lg font-bold">{a.label}</p>
                <p className="text-xs opacity-70">{a.hint}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

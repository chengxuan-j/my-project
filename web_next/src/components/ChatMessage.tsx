'use client';

import { EMOTION_LABEL } from '@/components/EmotionChart';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  emotion?: string;
  riskLevel?: string;
  intent?: string;
  scene?: string;
  topic?: string;
  need?: string;
  action?: string;
  actionReason?: string;
  recalledMemories?: string[];
  timestamp?: number;
}

const EMOTION_EMOJI: Record<string, string> = {
  happy: '😊',
  sad: '😢',
  anxious: '😟',
  lonely: '😔',
  calm: '😌',
  angry: '😠',
  neutral: '😐',
  bored: '😪',
  tired: '😩',
  nostalgic: '🥹',
  grateful: '🥰',
  worried: '😟',
};

const SCENE_LABEL: Record<string, string> = {
  alone: '独自在家',
  conversation: '聊天中',
  family: '与家人',
  outdoors: '外出',
  sleep: '休息/睡眠',
  meal: '用餐',
  health: '健康相关',
};
const INTENT_LABEL: Record<string, string> = {
  casual_chat: '闲聊',
  emotional_sharing: '倾诉情绪',
  question: '提问',
  music_request: '想听歌',
  story_request: '想听故事',
  game_request: '想玩游戏',
  greeting: '打招呼',
  memory_recall: '回忆往事',
  advice_request: '寻求建议',
  family_talk: '聊家人',
  health_concern: '健康担忧',
  safety_alert: '安全提醒',
  other: '其他',
};
const ACTION_LABEL: Record<string, string> = {
  comfort: '安抚',
  encourage: '鼓励',
  listen: '倾听',
  suggest_activity: '建议活动',
  recommend_music: '推荐音乐',
  recommend_story: '推荐故事',
  play_game: '陪玩游戏',
  give_advice: '给出建议',
  ask_back: '追问关心',
  safety_remind: '安全提醒',
  health_remind: '健康提醒',
  memory_recall: '唤起回忆',
  neutral_chat: '轻松聊天',
};

function label(v: string | undefined, map: Record<string, string>): string {
  if (!v) return '';
  return map[v] ? `${map[v]}（${v}）` : v;
}

export function ChatMessage({ message }: { message: Message }) {
  const isUser = message.role === 'user';
  const emoji = message.emotion ? EMOTION_EMOJI[message.emotion] || '💭' : null;
  const isRisk = message.riskLevel && message.riskLevel !== 'none' && message.riskLevel !== 'low';

  const showChain =
    message.role === 'assistant' &&
    (message.intent ||
      message.scene ||
      message.action ||
      message.topic ||
      (message.recalledMemories && message.recalledMemories.length > 0));

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      <div
        className={`max-w-[80%] rounded-2xl px-5 py-3 shadow-sm leading-relaxed ${
          isUser
            ? 'bg-warm-primary text-white rounded-br-sm'
            : isRisk
              ? 'bg-red-50 text-gray-900 border-2 border-red-400 rounded-bl-sm'
              : 'bg-white text-gray-900 border border-warm-light rounded-bl-sm'
        }`}
      >
        {!isUser && (
          <div className="text-sm mb-1 opacity-70 flex items-center gap-2">
            <span>🌻 陪伴 AI</span>
            {emoji && <span title={`情绪: ${message.emotion}`}>{emoji}</span>}
          </div>
        )}
        <div className="whitespace-pre-wrap break-words">{message.content}</div>

        {/* 决策链：AI 为什么这么说（可折叠） */}
        {showChain && (
          <details className="mt-2 border-t border-warm-light pt-2">
            <summary className="cursor-pointer select-none text-warm-primary font-medium text-sm">
              🌻 我为什么这么说
            </summary>
            <div className="mt-2 space-y-1 text-sm text-gray-700">
              {message.emotion && (
                <div>
                  💗 我感觉到你：{EMOTION_LABEL[message.emotion] || message.emotion}{' '}
                  {emoji}
                </div>
              )}
              {(message.intent || message.scene || message.topic) && (
                <div>
                  🧭 你当时：
                  {label(message.intent, INTENT_LABEL)}
                  {message.scene ? ` · 场景 ${label(message.scene, SCENE_LABEL)}` : ''}
                  {message.topic ? ` · 话题 ${message.topic}` : ''}
                </div>
              )}
              {message.action && (
                <div>
                  🤝 我的做法：{label(message.action, ACTION_LABEL)}
                  {message.actionReason ? ` —— ${message.actionReason}` : ''}
                </div>
              )}
              {message.recalledMemories && message.recalledMemories.length > 0 && (
                <div>
                  💭 我记起了：
                  <div className="flex flex-wrap gap-1 mt-1">
                    {message.recalledMemories.map((m, i) => (
                      <span
                        key={i}
                        className="px-2 py-0.5 bg-warm-light rounded-lg text-xs text-gray-700"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}
      </div>
    </div>
  );
}

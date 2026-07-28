import type { CareEvent } from '../types';

// agent P2：顯示 LangGraph agent（目前 shadow 模式）對事件的建議判斷，僅供人工複判參考，
// 不代表最終判定（人工判定見 StatusTag／event.verdict）。ai_verdict=null 時不渲染。
const AI_VERDICT_LABEL: Record<'true_alarm' | 'false_alarm', string> = {
  true_alarm: 'AI 建議：疑似跌倒',
  false_alarm: 'AI 建議：可能為誤報',
};

// 建議性質、非緊急，比照 tokens.css 的 --notice（僅限未讀／待辦等非緊急徽章）
const BADGE_STYLE = 'border border-[var(--notice)] bg-[var(--notice-bg)] text-[var(--notice)]';

export function AiSuggestionBadge({ event }: { event: CareEvent }) {
  if (!event.ai_verdict) return null;

  const label = AI_VERDICT_LABEL[event.ai_verdict];
  const confidenceText =
    event.ai_confidence != null ? `（信心 ${event.ai_confidence.toFixed(2)}）` : '';

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_STYLE}`}
    >
      {label}
      {confidenceText}
    </span>
  );
}

export default AiSuggestionBadge;

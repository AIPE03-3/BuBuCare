import type { EnvScoreLevel } from '../types';

export function getEnvScoreLevel(score: number): EnvScoreLevel {
  if (score >= 90) return '良好';
  if (score >= 70) return '注意';
  if (score >= 40) return '警示';
  return '危險';
}

export function getScoreTrendText(current: number, previous: number): string {
  const diff = current - previous;
  const direction = diff >= 0 ? '升' : '降';
  return `較昨日${direction} ${Math.abs(diff)} 分`;
}

// 等級 → 語意色 Tailwind class，供 EnvScoreLevelBadge 與其他需要「等級同色」的欄位（如評分歷史表分數欄）共用，避免各自寫一份對照。
export const LEVEL_TEXT_CLASS: Record<EnvScoreLevel, string> = {
  良好: 'text-[var(--success)]',
  注意: 'text-[var(--brand)]',
  警示: 'text-[var(--warning)]',
  危險: 'text-[var(--danger)]',
};

// 同一份對照的 CSS 變數名版本，供 Recharts（resolveCssVar）等需要實際色碼字串的地方使用。
export const LEVEL_COLOR_VAR: Record<EnvScoreLevel, string> = {
  良好: '--success',
  注意: '--brand',
  警示: '--warning',
  危險: '--danger',
};

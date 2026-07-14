import type { EnvScore } from '../types';

export interface EnvScoreGroups {
  danger: EnvScore[];
  warning: EnvScore[];
  offline: EnvScore[];
  normal: EnvScore[];
}

export function groupEnvScores(scores: EnvScore[]): EnvScoreGroups {
  return {
    danger: scores.filter((s) => s.online && s.level === '危險'),
    warning: scores.filter((s) => s.online && s.level === '警示'),
    offline: scores.filter((s) => !s.online),
    normal: scores.filter((s) => s.online && (s.level === '良好' || s.level === '注意')),
  };
}

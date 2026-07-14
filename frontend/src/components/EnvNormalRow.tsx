import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getEnvScoreDetail } from '../api/envScores';
import type { EnvScore } from '../types';

interface EnvNormalRowProps {
  score: EnvScore;
}

function trendArrow(current: number, previous: number | null): string {
  if (previous === null || current === previous) return '—';
  return current > previous ? '↑' : '↓';
}

export function EnvNormalRow({ score }: EnvNormalRowProps) {
  const navigate = useNavigate();
  const [previousScore, setPreviousScore] = useState<number | null>(null);

  useEffect(() => {
    getEnvScoreDetail(score.score_id).then((detail) => setPreviousScore(detail?.previousScore ?? null));
  }, [score.score_id]);

  return (
    <div
      onClick={() => navigate(`/environment/${score.score_id}`)}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-4 py-2 text-sm transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--success)]" />
      <span className="flex-1 text-[var(--text-primary)]">
        {score.camera.zone}・{score.camera.name}
      </span>
      <span aria-hidden="true" className="text-[var(--text-muted)]">
        {trendArrow(score.total_score ?? 0, previousScore)}
      </span>
      <span className="w-8 text-right font-medium text-[var(--text-primary)]">{score.total_score}</span>
    </div>
  );
}

export default EnvNormalRow;

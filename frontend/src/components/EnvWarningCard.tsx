import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getEnvScoreDetail } from '../api/envScores';
import type { EnvScore } from '../types';
import { EnvScoreLevelBadge } from './EnvScoreLevelBadge';
import { getScoreTrendText } from '../utils/envScore';

interface EnvWarningCardProps {
  score: EnvScore;
}

export function EnvWarningCard({ score }: EnvWarningCardProps) {
  const navigate = useNavigate();
  const [previousScore, setPreviousScore] = useState<number | null>(null);

  useEffect(() => {
    getEnvScoreDetail(score.score_id).then((detail) => setPreviousScore(detail?.previousScore ?? null));
  }, [score.score_id]);

  const current = score.total_score ?? 0;
  const trendText = previousScore !== null ? getScoreTrendText(current, previousScore) : null;
  const isDown = previousScore !== null && current < previousScore;

  return (
    <div
      onClick={() => navigate(`/environment/${score.score_id}`)}
      className="flex cursor-pointer items-center justify-between gap-4 rounded-xl border-2 border-[var(--warning)] bg-[var(--bg-surface)] p-4 transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-2">
          <EnvScoreLevelBadge level="警示" />
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {score.camera.zone}・{score.camera.name}
          </span>
        </div>
        {score.risk_factors.length > 0 && (
          <p className="text-sm text-[var(--text-secondary)]">{score.risk_factors[0]}</p>
        )}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="text-[40px] font-semibold leading-none text-[var(--warning)]">{score.total_score}</span>
        {trendText && (
          <span className="flex items-center gap-1 text-xs text-[var(--text-muted)]">
            {isDown && <span aria-hidden="true">↓</span>}
            {trendText}
          </span>
        )}
      </div>
    </div>
  );
}

export default EnvWarningCard;

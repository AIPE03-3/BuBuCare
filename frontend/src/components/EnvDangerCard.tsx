import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer } from 'recharts';
import { getEnvScoreDetail } from '../api/envScores';
import type { EnvScore } from '../types';
import { EnvScoreLevelBadge } from './EnvScoreLevelBadge';
import { resolveCssVar } from '../utils/cssVar';

const DANGER_THRESHOLD = 39;

interface EnvDangerCardProps {
  score: EnvScore;
}

export function EnvDangerCard({ score }: EnvDangerCardProps) {
  const navigate = useNavigate();
  const [history, setHistory] = useState<{ date: string; score: number }[]>([]);

  useEffect(() => {
    getEnvScoreDetail(score.score_id).then((detail) => setHistory(detail?.history ?? []));
  }, [score.score_id]);

  const firstScore = history[0]?.score ?? score.total_score ?? 0;
  const lastScore = score.total_score ?? 0;
  const drop = firstScore - lastScore;
  const trendText = drop >= 0 ? `近 7 日降 ${drop} 分` : `近 7 日升 ${Math.abs(drop)} 分`;

  return (
    <div
      onClick={() => navigate(`/environment/${score.score_id}`)}
      className="flex cursor-pointer flex-col gap-3 rounded-xl border-2 border-[var(--danger)] bg-[var(--bg-surface)] p-4 transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <EnvScoreLevelBadge level="危險" />
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {score.camera.zone}・{score.camera.name}
          </span>
        </div>
        <span className="text-[40px] font-semibold leading-none text-[var(--danger)]">{score.total_score}</span>
      </div>

      {score.risk_factors.length > 0 && (
        <p className="text-sm text-[var(--text-secondary)]">{score.risk_factors[0]}</p>
      )}

      <div className="h-32 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <ReferenceArea y1={0} y2={DANGER_THRESHOLD} fill={resolveCssVar('--danger-bg')} fillOpacity={0.5} />
            <ReferenceLine y={DANGER_THRESHOLD} stroke={resolveCssVar('--danger')} strokeDasharray="4 4" />
            <Line type="monotone" dataKey="score" stroke={resolveCssVar('--danger')} strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <p className="text-xs text-[var(--text-muted)]">{trendText}</p>
    </div>
  );
}

export default EnvDangerCard;

import { useNavigate } from 'react-router-dom';
import type { EnvScore } from '../types';
import { formatOfflineDuration } from '../utils/time';

interface EnvOfflineRowProps {
  score: EnvScore;
  now: number;
}

export function EnvOfflineRow({ score, now }: EnvOfflineRowProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/environment/${score.score_id}`)}
      className="flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--border)] bg-transparent px-4 py-2 text-sm text-[var(--offline)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <span aria-hidden="true">📵</span>
      <span className="inline-flex items-center rounded-full border border-[var(--offline)] px-2 py-0.5 text-xs font-medium text-[var(--offline)]">
        離線
      </span>
      <span className="text-[var(--text-primary)]">
        {score.camera.zone}・{score.camera.name}
      </span>
      <span className="text-[var(--text-muted)]">{formatOfflineDuration(score.assessed_at, now)}</span>
    </div>
  );
}

export default EnvOfflineRow;

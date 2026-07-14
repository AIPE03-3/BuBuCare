import type { EnvScoreLevel } from '../types';
import { LEVEL_TEXT_CLASS } from '../utils/envScore';

const LEVEL_DOT_CLASS: Record<EnvScoreLevel, string> = {
  良好: 'bg-[var(--success)]',
  注意: 'bg-[var(--brand)]',
  警示: 'bg-[var(--warning)]',
  危險: 'bg-[var(--danger)]',
};

interface EnvScoreLevelBadgeProps {
  level: EnvScoreLevel;
}

export function EnvScoreLevelBadge({ level }: EnvScoreLevelBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm font-medium">
      <span aria-hidden="true" className={`h-2 w-2 rounded-sm ${LEVEL_DOT_CLASS[level]}`} />
      <span className={LEVEL_TEXT_CLASS[level]}>{level}</span>
    </span>
  );
}

export default EnvScoreLevelBadge;

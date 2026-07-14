import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';
import { formatTime } from '../utils/time';

interface ResolvedRowProps {
  event: CareEvent;
}

export function ResolvedRow({ event }: ResolvedRowProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/events/${event.id}`)}
      className="flex cursor-pointer items-center gap-2 rounded-lg bg-[var(--bg-surface-2)] px-4 py-2 text-sm text-[var(--text-muted)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <span aria-hidden="true" className="text-[var(--offline)]">
        ✓
      </span>
      <span>
        {event.camera.zone}（{event.camera.name}）
      </span>
      <span>{formatTime(event.occurred_at)}</span>
    </div>
  );
}

export default ResolvedRow;

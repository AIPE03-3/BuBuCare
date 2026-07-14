import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';
import { CAMERA_LABEL } from '../types';
import { StatusTag } from './StatusTag';
import { formatElapsedMinutes } from '../utils/time';
import { hasEscalatedFlag } from '../utils/eventFlags';

interface ActionRequiredCardProps {
  event: CareEvent;
  now: number;
  onAcknowledge: (event: CareEvent) => void;
}

export function ActionRequiredCard({ event, now, onAcknowledge }: ActionRequiredCardProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/events/${event.id}`)}
      className="flex cursor-pointer items-center gap-4 rounded-xl border-2 border-[var(--danger)] bg-[var(--bg-surface)] p-4 transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <div className="flex h-20 w-28 shrink-0 items-center justify-center rounded-lg bg-[var(--bg-surface-2)] text-center text-xs text-[var(--text-muted)]">
        {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
      </div>

      <div className="flex flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-[var(--text-primary)]">
            跌倒　{event.camera.zone}（{event.camera.name}）
          </p>
          {hasEscalatedFlag(event) && (
            <span aria-hidden="true" title="事件曾升級並通知當日值班組長">
              🚩
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <span>{formatElapsedMinutes(event.occurred_at, now)}</span>
          <StatusTag status={event.status} ackDeadline={event.ack_deadline} now={now} />
          {event.assignee && <span className="text-[var(--text-primary)]">已接手 {event.assignee}</span>}
        </div>
      </div>

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onAcknowledge(event);
        }}
        className="flex shrink-0 items-center gap-1 rounded-md bg-[var(--brand)] px-4 py-2 text-sm text-white transition-colors duration-150"
      >
        接手
        <span aria-hidden="true">›</span>
      </button>
    </div>
  );
}

export default ActionRequiredCard;

import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';
import { CAMERA_LABEL } from '../types';
import { StatusTag } from './StatusTag';
import { formatElapsedMinutes } from '../utils/time';
import { getEventTypeLabel, hasEscalatedFlag } from '../utils/eventFlags';
import { FlagIcon } from './icons';

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
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          navigate(`/events/${event.id}`);
        }
      }}
      role="button"
      tabIndex={0}
      className="flex cursor-pointer flex-col gap-3 rounded-2xl border-2 border-[var(--danger)] bg-[var(--bg-surface)] p-4 shadow-sm transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2 sm:flex-row sm:items-center sm:gap-4"
    >
      <div className="flex h-16 w-full items-center justify-center rounded-lg bg-[var(--bg-surface-2)] text-center text-xs text-[var(--text-muted)] sm:h-20 sm:w-28 sm:shrink-0">
        {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <p className="text-sm font-medium text-[var(--text-primary)]">
            {getEventTypeLabel(event)}　{event.camera.zone}（{event.camera.name}）
          </p>
          {hasEscalatedFlag(event) && (
            <span title="事件曾升級並通知當日值班組長" className="shrink-0">
              <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--text-secondary)]">
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
        className="flex w-full shrink-0 items-center justify-center gap-1 rounded-md bg-[var(--brand)] px-4 py-2 text-sm text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2 sm:w-auto"
      >
        接手
        <span aria-hidden="true">›</span>
      </button>
    </div>
  );
}

export default ActionRequiredCard;

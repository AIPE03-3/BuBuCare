import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';
import { StatusTag } from './StatusTag';
import { formatElapsedMinutes } from '../utils/time';
import { hasEscalatedFlag } from '../utils/eventFlags';

interface InProgressRowProps {
  event: CareEvent;
  now: number;
}

export function InProgressRow({ event, now }: InProgressRowProps) {
  const navigate = useNavigate();

  return (
    <div
      onClick={() => navigate(`/events/${event.id}`)}
      className="flex cursor-pointer items-center gap-3 rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <p className="flex-1 text-sm text-[var(--text-primary)]">
        跌倒　{event.camera.zone}（{event.camera.name}）　{formatElapsedMinutes(event.occurred_at, now)}
      </p>

      {hasEscalatedFlag(event) && (
        <span aria-hidden="true" title="事件曾升級並通知當日值班組長">
          🚩
        </span>
      )}

      <StatusTag status={event.status} ackDeadline={event.ack_deadline} now={now} />

      {event.assignee && <span className="text-sm text-[var(--text-primary)]">{event.assignee}</span>}

      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          console.log('回報完成', event.id);
        }}
        className="shrink-0 rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-xs text-[var(--brand)] transition-colors duration-150"
      >
        回報完成
      </button>
    </div>
  );
}

export default InProgressRow;

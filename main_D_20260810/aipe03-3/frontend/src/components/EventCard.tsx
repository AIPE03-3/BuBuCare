import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';
import { StatusTag } from './StatusTag';
import { AiSuggestionBadge } from './AiSuggestionBadge';
import { formatElapsedMinutes, formatTime } from '../utils/time';
import { getEventTypeLabel, hasEscalatedFlag } from '../utils/eventFlags';
import { FlagIcon } from './icons';
import { useEvents } from '../hooks/eventsContext';

function getNotificationNote(event: CareEvent): { text: string; className: string } | null {
  if (event.escalated_to) {
    // 曾升級且仍待處理（pending）時以 danger 提示，否則為淡色歷史註記。
    const className =
      event.status === 'pending' ? 'text-[var(--danger)]' : 'text-[var(--text-muted)]';
    return { text: `逾時未接手，已升級通知${event.escalated_to}`, className };
  }
  if (event.status === 'pending' && event.notified_to) {
    return { text: `已通知 ${event.notified_to}`, className: '' };
  }
  return null;
}

interface EventCardProps {
  event: CareEvent;
  now: number;
  highlighted: boolean;
  onAcknowledge: (event: CareEvent) => void;
}

export function EventCard({ event, now, highlighted, onAcknowledge }: EventCardProps) {
  const navigate = useNavigate();
  const { handleConfirmAiFalseAlarm } = useEvents();

  const note = getNotificationNote(event);
  const escalated = hasEscalatedFlag(event);
  const canAcknowledge = event.status === 'pending';
  // AI 建議可能為誤報，且事件還沒被人工判定過（pending）時才給一鍵確認，避免對已結案事件亂改狀態
  const canConfirmAiFalseAlarm = event.status === 'pending' && event.ai_verdict === 'false_alarm';

  return (
    <div
      id={`event-card-${event.id}`}
      onClick={() => navigate(`/events/${event.id}`)}
      className={`w-full cursor-pointer rounded-xl border border-[var(--border)] p-4 text-left transition-colors duration-150 hover:bg-[var(--brand-soft)] ${
        highlighted ? 'bg-[var(--brand-soft)]' : 'bg-[var(--bg-surface)]'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-[var(--text-primary)]">
          地點：{event.camera.zone}（{event.camera.name}）　類型：{getEventTypeLabel(event)}　通報時間：{formatTime(event.occurred_at)}
        </p>
        {escalated && (
          <span title="事件曾升級並通知當日值班組長" className="shrink-0">
            <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
          </span>
        )}
      </div>
      <p className="mt-1 flex items-center gap-1 text-sm text-[var(--text-secondary)]">
        <span>信心：{event.confidence.toFixed(2)}　狀態：</span>
        <StatusTag status={event.status} verdict={event.verdict} ackDeadline={event.ack_deadline} now={now} />
        {event.assignee && <span className="text-sm text-[var(--text-primary)]">　已接手 {event.assignee}</span>}
        <span>　距今已過：{formatElapsedMinutes(event.occurred_at, now)}</span>
        {note && <span className={note.className}>　{note.text}</span>}
      </p>

      {event.ai_verdict && (
        <p className="mt-1">
          <AiSuggestionBadge event={event} />
        </p>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {canAcknowledge && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onAcknowledge(event);
            }}
            className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-xs text-[var(--brand)] transition-colors duration-150"
          >
            接手
          </button>
        )}
        {canConfirmAiFalseAlarm && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              handleConfirmAiFalseAlarm(event);
            }}
            className="rounded-md border border-[var(--offline)] bg-transparent px-3 py-1 text-xs text-[var(--offline)] transition-colors duration-150"
          >
            確認誤報
          </button>
        )}
      </div>
    </div>
  );
}

export default EventCard;

import { useNavigate } from 'react-router-dom';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { FlagIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { hasEscalatedFlag } from '../utils/eventFlags';

export function EventCenterUnresolved() {
  const navigate = useNavigate();
  const { events, now } = useEvents();
  const inProgress = events.filter((event) => event.status === 'in_progress');

  if (inProgress.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">目前沒有處理中的事件</p>;
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
      <table className="w-full text-left text-sm">
        <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
          <tr>
            <th className="px-4 py-3 font-medium">事件編號</th>
            <th className="px-4 py-3 font-medium">事件</th>
            <th className="px-4 py-3 font-medium">事發地點</th>
            <th className="px-4 py-3 font-medium">事發時間</th>
            <th className="px-4 py-3 font-medium">事件狀態</th>
          </tr>
        </thead>
        <tbody>
          {inProgress.map((event) => (
            <tr
              key={event.id}
              onClick={() => navigate(`/events/${event.id}`)}
              className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
            >
              <td className="px-4 py-3 text-[var(--text-secondary)]">{event.id}</td>
              <td className="px-4 py-3 text-[var(--text-primary)]">跌倒</td>
              <td className="px-4 py-3 text-[var(--text-primary)]">
                {event.camera.zone}（{event.camera.name}）
              </td>
              <td className="px-4 py-3 text-[var(--text-secondary)]">
                {formatDateTime(event.occurred_at)}
              </td>
              <td className="px-4 py-3">
                <span className="inline-flex items-center gap-1.5">
                  <EventStatusBadge event={event} now={now} />
                  {hasEscalatedFlag(event) && (
                    <span title="事件曾升級並通知當日值班組長">
                      <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
                    </span>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default EventCenterUnresolved;

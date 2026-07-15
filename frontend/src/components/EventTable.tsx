import { useNavigate } from 'react-router-dom';
import { EventStatusBadge } from './EventStatusBadge';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import type { CareEvent } from '../types';

// 事件表格：事件編號/事件/事發地點/事發時間/事件狀態。已結報事件、誤報紀錄等清單共用。
export function EventTable({ events, emptyMessage }: { events: CareEvent[]; emptyMessage: string }) {
  const navigate = useNavigate();
  const { now } = useEvents();

  if (events.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">{emptyMessage}</p>;
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
          {events.map((event) => (
            <tr
              key={event.id}
              onClick={() => navigate(`/events/${event.id}`)}
              className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
            >
              <td className="px-4 py-3 text-[var(--text-secondary)]">{event.id}</td>
              <td className="px-4 py-3 text-[var(--text-primary)]">{getEventTypeLabel(event)}</td>
              <td className="px-4 py-3 text-[var(--text-primary)]">
                {event.camera.zone}（{event.camera.name}）
              </td>
              <td className="px-4 py-3 text-[var(--text-secondary)]">
                {formatDateTime(event.occurred_at)}
              </td>
              <td className="px-4 py-3">
                <EventStatusBadge event={event} now={now} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default EventTable;

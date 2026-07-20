import { EventStatusBadge } from './EventStatusBadge';
import { ResponsiveEventList, type EventListColumn } from './ResponsiveEventList';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import type { CareEvent } from '../types';

// 事件表格：事件編號/事件/事發地點/事發時間/事件狀態。已結報事件、誤報紀錄等清單共用。
// 版型（桌機表格／手機卡片）交由 ResponsiveEventList 處理，本檔只定義欄位內容。
export function EventTable({ events, emptyMessage }: { events: CareEvent[]; emptyMessage: string }) {
  const { now } = useEvents();

  const columns: EventListColumn[] = [
    {
      key: 'id',
      header: '事件編號',
      cell: (event) => <span className="text-[var(--text-secondary)]">{event.id}</span>,
    },
    {
      key: 'type',
      header: '事件',
      cell: (event) => <span className="text-[var(--text-primary)]">{getEventTypeLabel(event)}</span>,
    },
    {
      key: 'location',
      header: '事發地點',
      cell: (event) => (
        <span className="text-[var(--text-primary)]">
          {event.camera.zone}（{event.camera.name}）
        </span>
      ),
    },
    {
      key: 'occurred_at',
      header: '事發時間',
      cell: (event) => (
        <span className="text-[var(--text-secondary)]">{formatDateTime(event.occurred_at)}</span>
      ),
    },
    {
      key: 'status',
      header: '事件狀態',
      cell: (event) => <EventStatusBadge event={event} now={now} />,
    },
  ];

  return (
    <ResponsiveEventList
      events={events}
      columns={columns}
      getRowHref={(event) => `/events/${event.id}`}
      emptyMessage={emptyMessage}
    />
  );
}

export default EventTable;

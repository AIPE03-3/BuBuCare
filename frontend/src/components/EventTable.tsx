import { EventStatusBadge } from './EventStatusBadge';
import { ResponsiveEventList, type EventListColumn } from './ResponsiveEventList';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import type { CareEvent } from '../types';

// 事件表格：事件編號/事件/事發地點/事發時間/事件狀態。已結報事件、誤報紀錄等清單共用。
// 版型（桌機表格／手機卡片）交由 ResponsiveEventList 處理，本檔只定義欄位內容。
// getRowHref：點列去向，預設 /events/:id（事件中心詳情）。歷史紀錄清單傳 /history/:id 導向唯讀歷史詳情。
export function EventTable({
  events,
  emptyMessage,
  getRowHref = (event) => `/events/${event.id}`,
}: {
  events: CareEvent[];
  emptyMessage: string;
  getRowHref?: (event: CareEvent) => string;
}) {
  const { now } = useEvents();

  const columns: EventListColumn[] = [
    {
      key: 'id',
      header: '事件編號',
      // 純展示用排序編號，非後端欄位：跟著目前列表順序現算，換頁/新事件進來會跟著變動（比照事件中心）
      cell: (_event, index) => <span className="text-[var(--text-secondary)]">{index + 1}</span>,
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
      getRowHref={getRowHref}
      emptyMessage={emptyMessage}
    />
  );
}

export default EventTable;

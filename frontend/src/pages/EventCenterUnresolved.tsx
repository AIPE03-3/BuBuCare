import { CountdownTimer } from '../components/CountdownTimer';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { FlagIcon } from '../components/icons';
import { ResponsiveEventList, type EventListColumn } from '../components/ResponsiveEventList';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime, formatFullDate } from '../utils/time';
import { getEventTypeLabel, hasEscalatedFlag } from '../utils/eventFlags';
import type { CareEvent } from '../types';

// getRowHref：點列的導向目標。預設進事件詳情頁；製作通報單頁改傳入通報單填寫路由，
// 讓同一份列表在不同頁面有不同去向，不必複製列表邏輯。
export function EventCenterUnresolved({
  getRowHref = (event: CareEvent) => `/events/${event.id}`,
}: {
  getRowHref?: (event: CareEvent) => string;
} = {}) {
  const { events, now } = useEvents();
  const inProgress = events.filter((event) => event.status === 'in_progress');

  const columns: EventListColumn[] = [
    {
      key: 'id',
      header: '事件編號',
      // 純展示用排序編號，非後端欄位：跟著目前列表順序現算，換頁/新事件進來會跟著變動
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
      key: 'deadline',
      header: '處理時限',
      cell: (event) => <CountdownTimer deadline={event.resolve_deadline} now={now} />,
    },
    {
      key: 'follow_up_deadline',
      header: '續報期限',
      cell: (event) =>
        event.follow_up_deadline ? (
          <span className="text-[var(--text-primary)]">
            {formatFullDate(event.follow_up_deadline)}
          </span>
        ) : (
          <span className="text-[var(--text-muted)]">—</span>
        ),
    },
    {
      key: 'status',
      header: '事件狀態',
      cell: (event) => (
        <span className="inline-flex items-center gap-1.5">
          <EventStatusBadge event={event} now={now} />
          {hasEscalatedFlag(event) && (
            <span title="事件曾升級並通知當日值班組長">
              <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
            </span>
          )}
        </span>
      ),
    },
  ];

  return (
    <ResponsiveEventList
      events={inProgress}
      columns={columns}
      getRowHref={getRowHref}
      emptyMessage="目前沒有處理中的事件"
    />
  );
}

export default EventCenterUnresolved;

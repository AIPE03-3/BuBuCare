import { useState } from 'react';
import { CountdownTimer } from '../components/CountdownTimer';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { AiSuggestionBadge } from '../components/AiSuggestionBadge';
import { FlagIcon } from '../components/icons';
import { ResponsiveEventList, type EventListColumn } from '../components/ResponsiveEventList';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime, formatFullDate } from '../utils/time';
import { getEventTypeLabel, hasEscalatedFlag } from '../utils/eventFlags';
import type { CareEvent } from '../types';

// getRowHref：點列的導向目標。預設進事件詳情頁；製作通報單頁改傳入通報單填寫路由，
// 讓同一份列表在不同頁面有不同去向，不必複製列表邏輯。
// showPending：連同待處理事件一起列出並附接手鈕。事件中心開（待處理的常駐出口），
// 製作通報單頁關（還沒接手不該先填通報單）。
// showAssignee：是否顯示「處理人」欄。通報單頁只是挑事件來填，不需要這欄。
export function EventCenterUnresolved({
  getRowHref = (event: CareEvent) => `/events/${event.id}`,
  showPending = false,
  showAssignee = false,
}: {
  getRowHref?: (event: CareEvent) => string;
  showPending?: boolean;
  showAssignee?: boolean;
} = {}) {
  const { events, now, handleAcknowledgeEvent, handleConfirmAiFalseAlarm } = useEvents();
  // 接手送出中的事件 id：送出期間停用該列按鈕，避免連點對同一筆送出兩次判定。
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const visibleEvents = events.filter((event) =>
    showPending ? event.status !== 'resolved' : event.status === 'in_progress',
  );

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
        <span className="inline-flex flex-wrap items-center gap-1.5">
          <EventStatusBadge event={event} now={now} />
          {hasEscalatedFlag(event) && (
            <span title="事件曾升級並通知當日值班組長">
              <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
            </span>
          )}
          {event.ai_verdict && <AiSuggestionBadge event={event} />}
          {/* 接手鈕併在徽章旁，不另開一欄——否則非待處理的列會排滿無意義的「—」 */}
          {showPending && event.status === 'pending' && (
            <button
              type="button"
              disabled={claimingId === event.id}
              // stopPropagation：不擋的話按接手會連帶觸發整列跳頁
              onClick={async (e) => {
                e.stopPropagation();
                setClaimingId(event.id);
                await handleAcknowledgeEvent(event);
                setClaimingId(null);
              }}
              className="rounded-lg bg-[var(--success)] px-2.5 py-1 text-xs font-medium text-white transition-colors duration-150 hover:opacity-90 disabled:opacity-60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--success)] focus-visible:ring-offset-2"
            >
              {claimingId === event.id ? '接手中…' : '接手'}
            </button>
          )}
          {/* agent P2：AI 建議可能為誤報時，一鍵採納（沿用既有 verdict+resolve 流程） */}
          {showPending && event.status === 'pending' && event.ai_verdict === 'false_alarm' && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleConfirmAiFalseAlarm(event);
              }}
              className="rounded-lg border border-[var(--offline)] px-2.5 py-1 text-xs font-medium text-[var(--offline)] transition-colors duration-150 hover:bg-[var(--bg-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--offline)] focus-visible:ring-offset-2"
            >
              確認誤報
            </button>
          )}
        </span>
      ),
    },
    // assignee 取自後端 verdict_by（員編），尚無人接手時為 null
    ...(showAssignee
      ? [
          {
            key: 'assignee',
            header: '處理人',
            cell: (event: CareEvent) =>
              event.assignee ? (
                <span className="text-[var(--text-primary)]">{event.assignee}</span>
              ) : (
                <span className="text-[var(--text-muted)]">—</span>
              ),
          },
        ]
      : []),
  ];

  return (
    <ResponsiveEventList
      events={visibleEvents}
      columns={columns}
      getRowHref={getRowHref}
      emptyMessage={showPending ? '目前沒有未結案的事件' : '目前沒有處理中的事件'}
    />
  );
}

export default EventCenterUnresolved;

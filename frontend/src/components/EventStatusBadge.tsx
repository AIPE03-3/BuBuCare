import type { CareEvent } from '../types';
import { REPORT_STAGE_LABEL } from '../types';
import { StatusTag } from './StatusTag';

// 事件狀態顯示：一旦有通報狀態（初報/續報/結報）即以通報狀態為準，否則顯示事件生命週期狀態（處理中等）。
// 詳情頁與未結案表格共用，確保同一筆事件狀態呈現一致。
export function EventStatusBadge({ event, now }: { event: CareEvent; now: number }) {
  if (event.report_stage) {
    return (
      <span className="inline-flex items-center rounded-full border border-[var(--brand)] px-2 py-0.5 text-xs font-medium text-[var(--brand)]">
        {REPORT_STAGE_LABEL[event.report_stage]}
      </span>
    );
  }
  return <StatusTag status={event.status} verdict={event.verdict} ackDeadline={event.ack_deadline} now={now} />;
}

export default EventStatusBadge;

import type { EventStatus, EventVerdict } from '../types';
import { STATUS_LABEL } from '../types';

const STATUS_STYLE: Record<EventStatus, string> = {
  pending: 'bg-[var(--warning-bg)] text-[var(--warning)]',
  in_progress: 'border border-[var(--text-primary)] text-[var(--text-primary)] bg-transparent',
  resolved: 'bg-[var(--success-bg)] text-[var(--success)]',
};

// 誤報（resolved + verdict=false_alarm）：灰字空心外框，不吃 resolved 的綠底。
const FALSE_ALARM_STYLE = 'border border-[var(--offline)] text-[var(--offline)] bg-transparent';
const FALSE_ALARM_LABEL = '誤報';

function formatOverdue(ackDeadline: string, now: number): string {
  const overdueSeconds = Math.max(0, Math.floor((now - new Date(ackDeadline).getTime()) / 1000));
  const minutes = Math.floor(overdueSeconds / 60);
  const seconds = overdueSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function isOverdue(status: EventStatus, ackDeadline: string | null | undefined, now: number): ackDeadline is string {
  return status === 'pending' && !!ackDeadline && now >= new Date(ackDeadline).getTime();
}

interface StatusTagProps {
  status: EventStatus;
  verdict?: EventVerdict;
  ackDeadline?: string | null;
  now: number;
}

export function StatusTag({ status, verdict, ackDeadline, now }: StatusTagProps) {
  // 誤報依 verdict 判斷（非 status）：resolved + false_alarm 顯示「誤報」灰空心標籤。
  const isFalseAlarm = status === 'resolved' && verdict === 'false_alarm';

  const label = isFalseAlarm
    ? FALSE_ALARM_LABEL
    : isOverdue(status, ackDeadline, now)
      ? `${STATUS_LABEL.pending} 逾時 ${formatOverdue(ackDeadline, now)}`
      : STATUS_LABEL[status];

  const style = isFalseAlarm ? FALSE_ALARM_STYLE : STATUS_STYLE[status];

  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
      {label}
    </span>
  );
}

export default StatusTag;

import type { NotificationStatus } from '../types';
import { NOTIFICATION_STATUS_LABEL } from '../types';

const NOTIFICATION_STATUS_STYLE: Record<NotificationStatus, string> = {
  delivered: 'bg-[var(--success-bg)] text-[var(--success)]',
  failed: 'bg-[var(--danger-bg)] text-[var(--danger)]',
};

interface NotificationStatusTagProps {
  status: NotificationStatus;
}

export function NotificationStatusTag({ status }: NotificationStatusTagProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${NOTIFICATION_STATUS_STYLE[status]}`}>
      {NOTIFICATION_STATUS_LABEL[status]}
    </span>
  );
}

export default NotificationStatusTag;

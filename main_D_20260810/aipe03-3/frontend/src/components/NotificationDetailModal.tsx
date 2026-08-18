import { createPortal } from 'react-dom';
import type { CareEvent } from '../types';
import { STATUS_LABEL } from '../types';
import { formatDate, formatTime } from '../utils/time';

interface NotificationDetailModalProps {
  event: CareEvent;
  onClose: () => void;
}

function DetailRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-2 text-sm last:border-b-0">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

export function NotificationDetailModal({ event, onClose }: NotificationDetailModalProps) {
  return createPortal(
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-4 sm:p-6">
      <div className="flex w-full max-w-[420px] max-h-[90vh] min-h-0 flex-col gap-2 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6">
        <h2 className="mb-2 text-lg font-semibold text-[var(--text-primary)]">事件摘要</h2>

        <DetailRow label="發生時間" value={`${formatDate(event.occurred_at)} ${formatTime(event.occurred_at)}`} />
        <DetailRow label="最終狀態" value={STATUS_LABEL[event.status]} />
        <DetailRow label="信心分數" value={event.confidence.toFixed(2)} />
        <DetailRow label="處理耗時" value={<span className="text-[var(--text-muted)]">－（暫未提供）</span>} />

        <button
          type="button"
          onClick={onClose}
          className="mt-4 rounded-md border border-[var(--text-secondary)] bg-transparent px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150"
        >
          關閉
        </button>
      </div>
    </div>,
    document.body,
  );
}

export default NotificationDetailModal;

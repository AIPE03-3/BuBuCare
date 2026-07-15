import { createPortal } from 'react-dom';

// 通用再確認彈窗：標題 + 訊息 + 確認／取消。沿用全站 modal 樣式（portal + overlay）。
interface ConfirmModalProps {
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmModal({
  title,
  message,
  confirmLabel = '確認',
  cancelLabel = '取消',
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  return createPortal(
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-6"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex w-full max-w-sm flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 shadow-lg">
        {title && <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>}
        <p className="text-sm text-[var(--text-primary)]">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-[var(--text-secondary)] bg-transparent px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default ConfirmModal;

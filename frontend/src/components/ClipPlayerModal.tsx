import { createPortal } from 'react-dom';
import { CAMERA_LABEL } from '../types';

interface ClipPlayerModalProps {
  clipPath: string | null;
  onClose: () => void;
}

// 共用片段播放彈窗：不接真串流，一律灰色占位框＋「事件快照（影像片段）」文字（CLAUDE.md 規定）。
export function ClipPlayerModal({ onClose }: ClipPlayerModalProps) {
  return createPortal(
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-6">
      <div className="flex w-[60vw] max-h-[90vh] min-h-0 flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">影片回放</h2>

        <div className="flex aspect-video min-h-0 w-full shrink items-center justify-center overflow-hidden rounded-xl bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
          {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
        </div>

        <button
          type="button"
          onClick={onClose}
          className="self-end rounded-md border border-[var(--text-secondary)] bg-transparent px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150"
        >
          關閉
        </button>
      </div>
    </div>,
    document.body,
  );
}

export default ClipPlayerModal;

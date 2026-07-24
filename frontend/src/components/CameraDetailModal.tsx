import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { Camera } from '../types';
import { CAMERA_LABEL, DETECTING_LABEL, OFFLINE_LABEL } from '../types';
import { CloseIcon, PencilIcon } from './icons';

interface CameraDetailModalProps {
  camera: Camera;
  isDetecting: boolean;
  onClose: () => void;
  onNameChange: (id: number, name: string) => void;
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-3 text-base last:border-b-0">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

export function CameraDetailModal({ camera, isDetecting, onClose, onNameChange }: CameraDetailModalProps) {
  // status !== 'online' 一律視為離線視覺（含 disabled 已停用）；本輪不細分 offline/disabled 呈現。
  const offline = camera.status !== 'online';
  const showDetecting = isDetecting && !offline;
  const [editing, setEditing] = useState(false);
  const [nameDraft, setNameDraft] = useState(camera.name);

  function startEditing() {
    setNameDraft(camera.name);
    setEditing(true);
  }

  function saveName() {
    const trimmed = nameDraft.trim();
    if (trimmed && trimmed !== camera.name) {
      onNameChange(camera.id, trimmed);
    }
    setEditing(false);
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-4 sm:p-6"
      onClick={onClose}
    >
      <div
        className="flex w-full max-w-[960px] max-h-[90vh] min-h-0 flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-8"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3">
          {editing ? (
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <input
                type="text"
                value={nameDraft}
                onChange={(e) => setNameDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveName();
                  if (e.key === 'Escape') setEditing(false);
                }}
                aria-label="鏡頭名稱"
                autoFocus
                className="min-w-0 flex-1 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1.5 text-2xl font-semibold text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
              />
              <button
                type="button"
                onClick={saveName}
                className="shrink-0 rounded-md bg-[var(--brand)] px-3 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
              >
                儲存
              </button>
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="shrink-0 rounded-md border border-[var(--text-secondary)] px-3 py-1.5 text-sm text-[var(--text-secondary)] transition-colors duration-150"
              >
                取消
              </button>
            </div>
          ) : (
            <div className="flex min-w-0 flex-1 items-center gap-2">
              <h2 className="min-w-0 truncate text-2xl font-semibold text-[var(--text-primary)]">{camera.name}</h2>
              <button
                type="button"
                onClick={startEditing}
                aria-label="編輯鏡頭名稱"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
              >
                <PencilIcon className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="關閉"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
          >
            <CloseIcon className="h-5 w-5" aria-hidden="true" />
          </button>
        </div>

        <div className="flex aspect-video w-full items-center justify-center rounded-xl bg-[var(--bg-surface-2)] text-center text-base text-[var(--text-muted)]">
          {CAMERA_LABEL.LIVE_PLACEHOLDER}
        </div>

        <div className="flex flex-col">
          <DetailRow label="所在區域" value={camera.zone} />
          <DetailRow label="狀態" value={offline ? OFFLINE_LABEL : '正常運作'} />
          {showDetecting && (
            <DetailRow label="偵測狀態" value={<span className="text-[var(--danger)]">{DETECTING_LABEL}</span>} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default CameraDetailModal;

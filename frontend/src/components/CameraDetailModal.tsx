import { useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { Camera } from '../types';
import { DETECTING_LABEL, OFFLINE_LABEL } from '../types';
import { LiveStream } from './LiveStream';
import { StreamModeToggle, type StreamMode } from './StreamModeToggle';
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
  const [streamMode, setStreamMode] = useState<StreamMode>('live');
  const streamUrl = streamMode === 'detect' ? camera.stream_url_detect : camera.stream_url;
  // 頻道名（LiveStream 拿去跟後端換串流權杖）。務必與 streamUrl 取同一個模式，
  // 否則換來的票對不上要看的頻道，MediaMTX 會回 401。
  const streamChannel =
    streamMode === 'detect' ? camera.stream_channel_detect : camera.stream_channel;

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

        {/* 只有真的有偵測頻道的鏡頭才給切換鈕；沒有的話按了也只是看到空畫面 */}
        <div className="flex items-center justify-end">
          {camera.stream_url_detect !== null && (
            <StreamModeToggle value={streamMode} onChange={setStreamMode} />
          )}
        </div>

        <div className="aspect-video w-full overflow-hidden rounded-xl">
          <LiveStream
            whepUrl={streamUrl}
            channel={streamChannel}
            emptyLabel={
              streamMode === 'detect' && camera.stream_url_detect === null
                ? '此鏡頭無 AI 偵測'
                : undefined
            }
          />
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

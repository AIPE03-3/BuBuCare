import { useState } from 'react';
import { createPortal } from 'react-dom';
import { DEMO_VIDEO_SRC } from './FullScreenAlert';
import type { CareEvent, FalseReportLabel } from '../types';

const FALSE_REPORT_LABELS: FalseReportLabel[] = ['坐地', '伸展', '彎腰', '攙扶', '其他'];

interface SuppressConfirmModalProps {
  event: CareEvent;
  onConfirm: (label: FalseReportLabel, note: string) => Promise<void>;
  onBack: () => void;
}

export function SuppressConfirmModal({ event, onConfirm, onBack }: SuppressConfirmModalProps) {
  const [videoEnded, setVideoEnded] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const [label, setLabel] = useState<FalseReportLabel | null>(null);
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const videoSrc = event.camera.stream_url ?? DEMO_VIDEO_SRC;
  const canConfirm = (videoEnded || videoError) && label !== null && !submitting;

  async function handleConfirm() {
    if (!label || !canConfirm) return;
    setSubmitting(true);
    await onConfirm(label, note);
  }

  return createPortal(
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-6">
      <div className="flex w-[60vw] max-h-[90vh] min-h-0 flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">確認誤報</h2>

        <div className="aspect-video min-h-0 w-full shrink overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
          {videoError ? (
            <div className="flex h-full items-center justify-center">
              <span className="text-[var(--text-muted)]">案件片段影像</span>
            </div>
          ) : (
            <video
              className="h-full w-full object-contain"
              src={videoSrc}
              autoPlay
              muted
              playsInline
              onEnded={() => setVideoEnded(true)}
              onError={() => setVideoError(true)}
            />
          )}
        </div>

        <div>
          <p className="mb-2 text-sm font-medium text-[var(--text-primary)]">誤報類型（必選）</p>
          <div className="flex flex-wrap gap-4">
            {FALSE_REPORT_LABELS.map((option) => (
              <label key={option} className="flex items-center gap-1.5 text-sm text-[var(--text-primary)]">
                <input
                  type="radio"
                  name="false-report-label"
                  value={option}
                  checked={label === option}
                  onChange={() => setLabel(option)}
                />
                {option}
              </label>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-2 text-sm font-medium text-[var(--text-primary)]">備註（選填）</p>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] p-2 text-sm text-[var(--text-primary)]"
          />
        </div>

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={handleConfirm}
            disabled={!canConfirm}
            className="min-w-0 flex-[2] rounded-md bg-[var(--offline)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50"
          >
            確認誤報並關閉
          </button>
          <button
            type="button"
            onClick={onBack}
            className="min-w-0 flex-1 rounded-md border border-[var(--text-secondary)] bg-transparent px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150"
          >
            返回警示
          </button>
        </div>

        {!videoEnded && !videoError && (
          <p className="text-xs text-[var(--text-muted)]">請完整播放影片一次以解鎖「確認誤報並關閉」。</p>
        )}
      </div>
    </div>,
    document.body,
  );
}

export default SuppressConfirmModal;

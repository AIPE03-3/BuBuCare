import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { notifyStaff } from '../services/eventActions';
import { SuppressConfirmModal } from './SuppressConfirmModal';
import type { CareEvent, FalseReportLabel } from '../types';

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function formatTimeWithSeconds(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function secondsSince(iso: string, now: number): number {
  return Math.max(0, Math.floor((now - new Date(iso).getTime()) / 1000));
}

// demo 素材：正式版改吃 activeAlert.stream_url（協定未定，先預留），檔案放 public/videos/fall-demo.mp4
export const DEMO_VIDEO_SRC = '/videos/fall-demo.mp4';

interface FullScreenAlertProps {
  alerts: CareEvent[];
  now: number;
  onAcknowledge: (event: CareEvent) => void;
  onSuppress: (event: CareEvent, label: FalseReportLabel, note: string) => Promise<void>;
}

export function FullScreenAlert({ alerts, now, onAcknowledge, onSuppress }: FullScreenAlertProps) {
  const [activeId, setActiveId] = useState(alerts[0]?.id);
  const [toastVisible, setToastVisible] = useState(false);
  const [failedVideoIds, setFailedVideoIds] = useState<Set<string>>(new Set());
  const [confirmStage, setConfirmStage] = useState<'idle' | 'confirming'>('idle');
  const [suppressModalOpen, setSuppressModalOpen] = useState(false);

  useEffect(() => {
    if (!toastVisible) return;
    const timer = setTimeout(() => setToastVisible(false), 3000);
    return () => clearTimeout(timer);
  }, [toastVisible]);

  const activeAlert = alerts.find((a) => a.id === activeId) ?? alerts[0];

  if (!activeAlert) return null;

  const videoSrc = activeAlert.camera.stream_url ?? DEMO_VIDEO_SRC;
  const videoError = failedVideoIds.has(activeAlert.id);

  function handleNotifyStaff() {
    void notifyStaff(activeAlert.id);
    setToastVisible(true);
  }

  async function handleSuppressConfirm(label: FalseReportLabel, note: string) {
    await onSuppress(activeAlert, label, note);
    setSuppressModalOpen(false);
  }

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4 bg-[var(--overlay)] p-6">
      <div className="flex w-[78vw] max-h-[90vh] min-h-0 flex-col rounded-xl border border-[var(--danger)] bg-[var(--bg-surface)] p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-[var(--danger-bg)] px-3 py-1 text-sm font-medium text-[var(--danger)]">
              需人工介入審查
            </span>
            {activeAlert.vlm_result === null && (
              <span className="text-xs text-[var(--text-muted)]">YOLO 高信心直通</span>
            )}
          </div>
          <span className="text-sm text-[var(--text-secondary)]">
            發生時間 {formatTimeWithSeconds(activeAlert.occurred_at)}
          </span>
        </div>

        <h2 className="mt-3 text-xl font-semibold text-[var(--text-primary)]">
          跌倒・{activeAlert.camera.zone}（{activeAlert.camera.name}）
        </h2>

        {activeAlert.escalated_to && (
          <p className="mt-2 text-sm text-[var(--danger)]">逾時未接手，已自動升級通知{activeAlert.escalated_to}</p>
        )}

        <div className="mt-4 aspect-video min-h-0 w-full shrink overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
          {videoError ? (
            <div className="flex h-full items-center justify-center">
              <span className="text-[var(--text-muted)]">案件片段影像</span>
            </div>
          ) : (
            <video
              key={activeAlert.id}
              className="h-full w-full object-contain"
              src={videoSrc}
              autoPlay
              muted
              loop
              playsInline
              onError={() => setFailedVideoIds((prev) => new Set(prev).add(activeAlert.id))}
            />
          )}
        </div>

        <div className="mt-4 flex gap-6 text-sm text-[var(--text-primary)]">
          <span>
            AI 判斷信心分數：
            <span className="text-[var(--danger)]">{activeAlert.confidence.toFixed(2)}</span>
          </span>
          <span>已經過 {secondsSince(activeAlert.occurred_at, now)} 秒</span>
        </div>

        {confirmStage === 'confirming' ? (
          <div className="mt-4 flex flex-wrap gap-3 rounded-md bg-[var(--danger-bg)] p-3">
            <button
              type="button"
              onClick={() => onAcknowledge(activeAlert)}
              className="min-w-0 flex-[2] rounded-md bg-[var(--danger)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
            >
              已點選前往處理，請再按一次送出
            </button>
            <button
              type="button"
              onClick={() => setConfirmStage('idle')}
              className="min-w-0 flex-1 rounded-md border border-[var(--danger)] bg-transparent px-3 py-2 text-sm text-[var(--danger)] transition-colors duration-150"
            >
              取消（誤點）
            </button>
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => setConfirmStage('confirming')}
              className="min-w-0 flex-[2] rounded-md bg-[var(--success)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
            >
              確認前往
            </button>
            <button
              type="button"
              onClick={handleNotifyStaff}
              className="min-w-0 flex-1 rounded-md border border-[var(--text-secondary)] bg-transparent px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150"
            >
              通知人員前往
            </button>
            <button
              type="button"
              onClick={() => setSuppressModalOpen(true)}
              className="min-w-0 rounded-md px-3 py-2 text-sm text-[var(--text-muted)] transition-colors duration-150"
            >
              誤報
            </button>
          </div>
        )}

        <p className="mt-3 text-xs text-[var(--text-muted)]">
          此警示不會自動消失；按「確認前往」後再次送出，事件同步轉為「已接手」。
        </p>
      </div>

      {alerts.length > 1 && (
        <div className="flex w-[78vw] flex-wrap gap-2">
          {alerts
            .filter((a) => a.id !== activeAlert.id)
            .map((a) => (
              <button
                key={a.id}
                type="button"
                onClick={() => setActiveId(a.id)}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1.5 text-xs text-[var(--text-secondary)] transition-colors duration-150"
              >
                {a.camera.zone}　{formatTimeWithSeconds(a.occurred_at)}
              </button>
            ))}
        </div>
      )}

      {toastVisible && (
        <div className="fixed right-6 bottom-6 z-[10000] rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm text-[var(--text-primary)]">
          功能串接中
        </div>
      )}

      {suppressModalOpen && (
        <SuppressConfirmModal
          event={activeAlert}
          onConfirm={handleSuppressConfirm}
          onBack={() => setSuppressModalOpen(false)}
        />
      )}
    </div>,
    document.body,
  );
}

export default FullScreenAlert;

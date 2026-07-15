import { useState } from 'react';
import { createPortal } from 'react-dom';
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

function formatMinutesSeconds(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}分${pad(seconds)}秒`;
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
  const [failedVideoIds, setFailedVideoIds] = useState<Set<string>>(new Set());
  const [confirmStage, setConfirmStage] = useState<'idle' | 'confirming'>('idle');
  const [suppressModalOpen, setSuppressModalOpen] = useState(false);

  const activeAlert = alerts.find((a) => a.id === activeId) ?? alerts[0];

  if (!activeAlert) return null;

  const videoSrc = activeAlert.camera.stream_url ?? DEMO_VIDEO_SRC;
  const videoError = failedVideoIds.has(activeAlert.id);

  async function handleSuppressConfirm(label: FalseReportLabel, note: string) {
    await onSuppress(activeAlert, label, note);
    setSuppressModalOpen(false);
  }

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4 bg-[var(--overlay)] p-6">
      <div className="flex w-fit max-w-[95vw] max-h-[90vh] min-h-0 flex-col rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 shadow-sm">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
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

        <div className="mt-4 flex flex-col gap-4 sm:flex-row">
          <div className="aspect-video h-[50vh] max-w-full shrink-0 overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
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

          <div className="flex flex-col gap-4 sm:h-[50vh] sm:w-56 sm:shrink-0">
            <div className="flex flex-col gap-3 text-sm text-[var(--text-primary)]">
              <div>
                <p>AI 判斷信心分數</p>
                <p className="text-[30px] font-semibold leading-tight text-[var(--danger)]">
                  {activeAlert.confidence.toFixed(2)}
                </p>
              </div>
              <div>
                <p>已經過</p>
                <p className="text-[30px] font-semibold leading-tight text-[var(--text-primary)]">
                  {formatMinutesSeconds(secondsSince(activeAlert.occurred_at, now))}
                </p>
              </div>
            </div>

            <div className="mt-auto flex flex-col gap-3">
              {/* 接手：單擊直接送出，不再二次確認 */}
              <button
                type="button"
                onClick={() => onAcknowledge(activeAlert)}
                className="rounded-md bg-[var(--success)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
              >
                接手處理
              </button>

              {/* 誤報：需二次確認才進入送出流程，避免把真跌倒誤標為誤報 */}
              {confirmStage === 'confirming' ? (
                <div className="flex flex-col gap-2 rounded-md bg-[var(--bg-surface-2)] p-3">
                  <p className="text-xs text-[var(--text-secondary)]">確定標記為誤報？再按一次進入誤報確認。</p>
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmStage('idle');
                      setSuppressModalOpen(true);
                    }}
                    className="rounded-md bg-[var(--offline)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
                  >
                    確認標記誤報
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmStage('idle')}
                    className="rounded-md border border-[var(--offline)] bg-transparent px-3 py-2 text-sm text-[var(--offline)] transition-colors duration-150"
                  >
                    取消
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmStage('confirming')}
                  className="rounded-md border border-[var(--offline)] bg-transparent px-3 py-2 text-sm text-[var(--offline)] transition-colors duration-150"
                >
                  誤報
                </button>
              )}
            </div>
          </div>
        </div>

        <p className="mt-3 text-xs text-[var(--text-muted)]">
          此警示不會自動消失；按「接手處理」即轉為「已接手」；標記「誤報」需二次確認。
        </p>
      </div>

      {alerts.length > 1 && (
        <div className="flex w-fit max-w-[95vw] flex-wrap gap-2">
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

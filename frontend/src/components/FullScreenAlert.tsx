import { useState } from 'react';
import { createPortal } from 'react-dom';
import { SuppressConfirmModal } from './SuppressConfirmModal';
import { useEventClipUrl } from '../hooks/useEventClipUrl';
import { EVENT_TYPE_LABEL } from '../types';
import type { CareEvent, EventType, FalseReportLabel } from '../types';

// 事件類型徽章配色：跌倒＝danger 實心紅（既有）；潛在危險（物件偵測）＝warning 淡橘（白字對比不足，改淡底深字，合 a11y）。
const TYPE_BADGE_CLASS: Record<EventType, string> = {
  fall: 'bg-[var(--danger)] text-white',
  hazard: 'bg-[var(--warning-bg)] text-[var(--warning)]',
};

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
  const { clipUrl, loading: clipLoading } = useEventClipUrl(activeAlert?.id);

  if (!activeAlert) return null;

  const videoSrc = clipUrl ?? DEMO_VIDEO_SRC;
  const videoError = failedVideoIds.has(activeAlert.id);

  async function handleSuppressConfirm(label: FalseReportLabel, note: string) {
    await onSuppress(activeAlert, label, note);
    setSuppressModalOpen(false);
  }

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4 overflow-y-auto bg-[var(--overlay)] p-4 sm:p-6">
      <div className="flex w-full max-w-3xl min-h-0 flex-col overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4 shadow-sm sm:p-6">
        {/* 標頭：鏡頭名稱＋事件類型標籤（跌倒／潛在危險，依類型變色）（左）／發生時間（右） */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">
              {activeAlert.camera.zone}（{activeAlert.camera.name}）
            </h2>
            <span
              className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${TYPE_BADGE_CLASS[activeAlert.event_type]}`}
            >
              {EVENT_TYPE_LABEL[activeAlert.event_type]}
            </span>
            {activeAlert.vlm_result === null && (
              <span className="text-xs text-[var(--text-muted)]">YOLO 高信心直通</span>
            )}
          </div>
          <span className="shrink-0 text-sm text-[var(--text-secondary)]">
            發生時間 {formatTimeWithSeconds(activeAlert.occurred_at)}
          </span>
        </div>

        {/* 影片：整寬置中 */}
        <div className="mt-4 aspect-video max-h-[55vh] w-full overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
          {clipLoading ? (
            <div className="flex h-full items-center justify-center">
              <span className="text-[var(--text-muted)]">載入中</span>
            </div>
          ) : videoError ? (
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

        {/* 底列：AI 信心分數＋已經過（左）／誤報＋接手處理（右） */}
        <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex gap-8 text-sm text-[var(--text-primary)]">
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

          {/* 誤報需二次確認：第一次按顯示確認列，避免把真跌倒誤標為誤報 */}
          {confirmStage === 'confirming' ? (
            <div className="flex flex-col gap-2 rounded-md bg-[var(--bg-surface-2)] p-3 sm:w-72">
              <p className="text-xs text-[var(--text-secondary)]">確定標記為誤報？再按一次進入誤報確認。</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setConfirmStage('idle');
                    setSuppressModalOpen(true);
                  }}
                  className="flex-1 rounded-md bg-[var(--offline)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
                >
                  確認標記誤報
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmStage('idle')}
                  className="flex-1 rounded-md border border-[var(--offline)] bg-transparent px-3 py-2 text-sm text-[var(--offline)] transition-colors duration-150"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <div className="flex gap-3">
              {/* 誤報：次要動作，灰底（比照圖片） */}
              <button
                type="button"
                onClick={() => setConfirmStage('confirming')}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface-2)] px-6 py-2 text-sm font-medium text-[var(--text-secondary)] transition-colors duration-150 hover:opacity-90"
              >
                誤報
              </button>
              {/* 接手：語意色 success 填色白字（依規範）；單擊直接送出，不再二次確認 */}
              <button
                type="button"
                onClick={() => onAcknowledge(activeAlert)}
                className="rounded-md bg-[var(--success)] px-6 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
              >
                接手處理
              </button>
            </div>
          )}
        </div>

        <p className="mt-3 text-xs text-[var(--text-muted)]">
          此警示不會自動消失；按「接手處理」即轉為「已接手」；標記「誤報」需二次確認。
        </p>
      </div>

      {alerts.length > 1 && (
        <div className="flex w-full max-w-3xl flex-wrap gap-2">
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

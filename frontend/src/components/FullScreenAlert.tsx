import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AiSuggestionBadge } from './AiSuggestionBadge';
import { CloseIcon } from './icons';
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

// 影片播完一次後，再等這麼久才自動關閉警示（給值班人員一點反應時間）。
const AUTO_DISMISS_DELAY_MS = 3000;

interface FullScreenAlertProps {
  alerts: CareEvent[];
  now: number;
  onAcknowledge: (event: CareEvent) => void;
  onSuppress: (event: CareEvent, label: FalseReportLabel, note: string) => Promise<void>;
  onDismiss: (event: CareEvent) => void;
}

export function FullScreenAlert({ alerts, now, onAcknowledge, onSuppress, onDismiss }: FullScreenAlertProps) {
  const [activeId, setActiveId] = useState(alerts[0]?.id);
  const [failedVideoIds, setFailedVideoIds] = useState<Set<string>>(new Set());
  const [confirmStage, setConfirmStage] = useState<'idle' | 'confirming'>('idle');
  const [suppressModalOpen, setSuppressModalOpen] = useState(false);
  const dismissTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const activeAlert = alerts.find((a) => a.id === activeId) ?? alerts[0];
  const { clipUrl, loading: clipLoading } = useEventClipUrl(activeAlert?.id);

  // 換到別筆警示或元件卸載時，把還沒到時間的自動關閉計時器清掉，避免關錯筆或記憶體洩漏。
  useEffect(() => {
    return () => {
      if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    };
  }, [activeAlert?.id]);

  if (!activeAlert) return null;

  const videoSrc = clipUrl ?? DEMO_VIDEO_SRC;
  const videoError = failedVideoIds.has(activeAlert.id);

  async function handleSuppressConfirm(label: FalseReportLabel, note: string) {
    await onSuppress(activeAlert, label, note);
    setSuppressModalOpen(false);
  }

  function handleVideoEnded() {
    if (dismissTimerRef.current) clearTimeout(dismissTimerRef.current);
    dismissTimerRef.current = setTimeout(() => onDismiss(activeAlert), AUTO_DISMISS_DELAY_MS);
  }

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center gap-4 overflow-y-auto bg-[var(--overlay)] p-4 sm:p-6">
      {/* 手動關閉：叉掉目前這筆警示，不做任何判定 */}
      <button
        type="button"
        onClick={() => onDismiss(activeAlert)}
        aria-label="關閉警示"
        className="absolute top-4 right-4 flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[var(--bg-surface)] text-[var(--text-secondary)] shadow-sm transition-colors duration-150 hover:bg-[var(--bg-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]"
      >
        <CloseIcon className="h-5 w-5" aria-hidden="true" />
      </button>

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
              playsInline
              controls
              onError={() => setFailedVideoIds((prev) => new Set(prev).add(activeAlert.id))}
              onEnded={handleVideoEnded}
            />
          )}
        </div>

        {/* VLM 判斷理由：只有走過二審的事件才有（YOLO 高信心直通的 vlm_result 是 null，
            標頭那顆「YOLO 高信心直通」小字已經說明過，這裡就整塊不渲染）。
            放在影片與操作列之間，是因為值班人員的閱讀順序是「看畫面 → 看理由 → 決定接手或誤報」；
            擠進底列會把「信心分數／已經過／兩顆按鈕」那排壓成三欄，反而讓要按的鈕變難找。
            description 來自後端的 vlm_summary（api/events.ts 的轉換），是純文字、可能很長，
            所以限高可捲——不讓它把下面的操作按鈕推出畫面外。 */}
        {activeAlert.vlm_result?.description && (
          <section
            aria-label="AI 影像分析判斷理由"
            className="mt-4 rounded-md border border-[var(--border)] bg-[var(--bg-surface-2)] p-3"
          >
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">AI 影像分析判斷理由</h3>
            <p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[var(--text-secondary)]">
              {activeAlert.vlm_result.description}
            </p>
          </section>
        )}

        {/* AI 二審判讀：agent（LangGraph）看過快照後的結論與理由。
            與上面那塊的差別——上面是「VLM 描述看到什麼」，這裡是「agent 判它是真是假、為什麼」。

            為什麼會有「判讀中」這個中間狀態：高信心跌倒走快速道，依規格不等 VLM 就先通報
            （docs/ARCHITECTURE.md §2「危急事件零延遲」），所以彈窗跳出的當下還沒有判讀。
            約 35 秒後 agent 判完，後端補寫同一筆並推 event_updated，這裡的文字就會自己換上。
            全程不重新彈窗、不打斷值班人員正在做的事。 */}
        <section
          aria-label="AI 二審判讀"
          className="mt-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface-2)] p-3"
        >
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">AI 二審判讀</h3>
            {/* 判定與信心分數重用事件清單那顆徽章，樣式與用色不另外發明一套 */}
            <AiSuggestionBadge event={activeAlert} />
          </div>
          {activeAlert.ai_reasoning ? (
            <p className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-[var(--text-secondary)]">
              {activeAlert.ai_reasoning}
            </p>
          ) : (
            <p className="mt-1 text-sm text-[var(--text-muted)]">
              AI 二審判讀中，完成後會自動顯示於此。
            </p>
          )}
        </section>

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
          影片播完會自動關閉，也可按右上角叉叉手動關閉；按「接手處理」即轉為「已接手」；標記「誤報」需二次確認。
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

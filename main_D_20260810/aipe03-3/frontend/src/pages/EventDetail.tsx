import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { CountdownTimer } from '../components/CountdownTimer';
import { DEMO_VIDEO_SRC } from '../components/FullScreenAlert';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { AiSuggestionBadge } from '../components/AiSuggestionBadge';
import { useEvents } from '../hooks/eventsContext';
import { useEventClipUrl } from '../hooks/useEventClipUrl';
import { getStoredReports } from '../api/reports';
import { formatDateTime, formatFullDate } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import type { CareEvent, SavedReport } from '../types';

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-3 text-sm last:border-b-0">
      <span className="shrink-0 text-[var(--text-secondary)]">{label}</span>
      <span className="min-w-0 text-right text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

export function EventDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { events, now, restoreEvent, handleConfirmAiFalseAlarm } = useEvents();
  const [videoError, setVideoError] = useState(false);
  const { clipUrl, loading: clipLoading } = useEventClipUrl(id);
  // 通報單紀錄走 async api（好換成後端 fetch），effect 載入；本頁進場時載一次即可。
  const [storedReports, setStoredReports] = useState<SavedReport[]>([]);

  useEffect(() => {
    if (!id) return;
    getStoredReports(id).then(setStoredReports);
  }, [id]);

  const event: CareEvent | undefined = events.find((e) => e.id === id);

  if (!event) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此事件</p>
      </div>
    );
  }

  const videoSrc = clipUrl ?? DEMO_VIDEO_SRC;
  // 誤報紀錄的事件：事件類型顯示誤報時選的類型，隱藏製作通報單，改提供「恢復事件」。
  const isFalseAlarm = event.verdict === 'false_alarm';
  const eventTypeLabel = getEventTypeLabel(event);
  // 每次通報都獨立儲存：最新一筆（陣列尾）決定 PDF 預覽鈕標籤；續報筆數用於「已續報次數」。
  const savedReport = storedReports.length > 0 ? storedReports[storedReports.length - 1] : null;
  const followUpCount = storedReports.filter((r) => r.form.reportType === '續報').length;
  // agent P2：AI 建議可能為誤報，且事件還沒被人工判定過（pending）時才給一鍵確認
  const canConfirmAiFalseAlarm = event.status === 'pending' && event.ai_verdict === 'false_alarm';

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件詳情</h1>

      {/* 單欄置中：影片 → 製作通報單按鈕 → 事件資訊，依序堆疊，寬度貼齊影片並置中。 */}
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        {/* 事發影片片段：維持 16:9 填滿（無灰邊）。 */}
        <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
          {clipLoading ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-sm text-[var(--text-muted)]">載入中</span>
            </div>
          ) : videoError ? (
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="text-sm text-[var(--text-muted)]">案件片段影像</span>
            </div>
          ) : (
            <video
              key={event.id}
              className="absolute inset-0 h-full w-full object-cover"
              src={videoSrc}
              autoPlay
              muted
              playsInline
              controls
              onError={() => setVideoError(true)}
            />
          )}
        </div>

        {/* 尚未建立任何通報單時才給「製作通報單」（初報）；已建立後改由下方續報／結報鈕推進，
            避免重複新增同型通報單而灌大續報次數。 */}
        {!isFalseAlarm && !savedReport && (
          <button
            type="button"
            onClick={() => navigate(`/reports/${event.id}`)}
            className="w-full rounded-md bg-[var(--brand)] px-4 py-2 text-center text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
          >
            製作通報單
          </button>
        )}

        {!isFalseAlarm && savedReport && (
          <button
            type="button"
            onClick={() => navigate(`/reports/${event.id}/preview`)}
            className="w-full rounded-md border border-[var(--brand)] bg-transparent px-4 py-2 text-center text-sm font-medium text-[var(--brand)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
          >
            預覽{savedReport.form.reportType} PDF
          </button>
        )}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">事件資訊</h2>
          <InfoRow label="事件編號" value={event.id} />
          <InfoRow label="事件" value={eventTypeLabel} />
          <InfoRow label="事發地點" value={`${event.camera.zone}（${event.camera.name}）`} />
          <InfoRow label="事發時間" value={formatDateTime(event.occurred_at)} />
          <InfoRow label="事件狀態" value={<EventStatusBadge event={event} now={now} />} />
          <InfoRow
            label="處理時限"
            value={<CountdownTimer deadline={event.resolve_deadline} now={now} />}
          />
          <InfoRow
            label="續報期限"
            value={event.follow_up_deadline ? formatFullDate(event.follow_up_deadline) : '—'}
          />
          {followUpCount > 0 && <InfoRow label="已續報次數" value={`${followUpCount} 次`} />}
          {isFalseAlarm && <InfoRow label="備註" value={event.false_alarm_note ?? '—'} />}
          {event.ai_verdict && <InfoRow label="AI 建議" value={<AiSuggestionBadge event={event} />} />}
          {event.ai_reasoning && <InfoRow label="AI 判斷理由" value={event.ai_reasoning} />}
        </div>

        {canConfirmAiFalseAlarm && (
          <button
            type="button"
            onClick={() => handleConfirmAiFalseAlarm(event)}
            className="w-full rounded-md border border-[var(--offline)] bg-transparent px-4 py-2 text-center text-sm font-medium text-[var(--offline)] transition-colors duration-150 hover:bg-[var(--bg-surface-2)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--offline)] focus-visible:ring-offset-2"
          >
            確認誤報（採納 AI 建議）
          </button>
        )}

        {/* 已初報或已續報時出現後續通報動作（可反覆續報，或結報結案）；點擊帶通報別導向填寫頁，
            該頁會載入既有通報單並自動勾選對應通報別。 */}
        {(event.report_stage === 'initial' || event.report_stage === 'follow_up') && (
          <div className="grid grid-cols-2 gap-2">
            {(['續報', '結報'] as const).map((type) => (
              <button
                key={type}
                type="button"
                onClick={() => navigate(`/reports/${event.id}?type=${encodeURIComponent(type)}`)}
                className="w-full rounded-md border border-[var(--brand)] bg-transparent px-4 py-2 text-center text-sm font-medium text-[var(--brand)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
              >
                {type}
              </button>
            ))}
          </div>
        )}

        {isFalseAlarm && (
          <button
            type="button"
            onClick={() => {
              restoreEvent(event.id);
              navigate('/events');
            }}
            className="w-full rounded-md bg-[var(--brand)] px-4 py-2 text-center text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
          >
            恢復事件
          </button>
        )}
      </div>
    </div>
  );
}

export default EventDetail;

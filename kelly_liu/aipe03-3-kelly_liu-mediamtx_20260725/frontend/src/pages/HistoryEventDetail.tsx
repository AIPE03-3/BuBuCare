import { useEffect, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { DEMO_VIDEO_SRC } from '../components/FullScreenAlert';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { ReportContent } from '../components/ReportContent';
import { useEvents } from '../hooks/eventsContext';
import { useEventClipUrl } from '../hooks/useEventClipUrl';
import { getStoredReports } from '../api/reports';
import { formatDateTime, formatFullDate } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import type { CareEvent, SavedReport } from '../types';

// 歷史事件詳情（唯讀）：與事件中心的 EventDetail 分開，避免點歷史事件跳回事件中心操作頁。
// 版型沿用 EventDetail（影片＋事件資訊），但移除所有推進操作（製作通報單／續報／結報／恢復事件），
// 並改為列出「同一筆事件的完整通報歷程」——初報→續報→結報逐筆，折疊時間軸點擊展開全文。

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-3 text-sm last:border-b-0">
      <span className="shrink-0 text-[var(--text-secondary)]">{label}</span>
      <span className="min-w-0 text-right text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// 單筆通報單：折疊卡片，summary 顯示通報別＋儲存時間，展開後為完整十一段內容。
function ReportHistoryItem({ report, index }: { report: SavedReport; index: number }) {
  return (
    <details className="group rounded-xl border border-[var(--border)] bg-[var(--bg-surface)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-sm">
        <span className="flex items-center gap-2">
          <span className="inline-flex items-center rounded-full bg-[var(--brand-soft)] px-2.5 py-0.5 text-xs font-medium text-[var(--brand)]">
            {report.form.reportType ?? `第 ${index + 1} 筆`}
          </span>
          <span className="text-[var(--text-secondary)]">{formatDateTime(report.savedAt)}</span>
        </span>
        <span className="text-xs text-[var(--text-muted)] transition-transform duration-150 group-open:rotate-90">
          ›
        </span>
      </summary>
      <div className="border-t border-[var(--border)] px-4 pb-4 pt-1">
        <ReportContent form={report.form} />
      </div>
    </details>
  );
}

export function HistoryEventDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { events, now } = useEvents();
  const [videoError, setVideoError] = useState(false);
  const { clipUrl, loading: clipLoading } = useEventClipUrl(id);
  // 通報歷程走 async api（好換成後端 fetch），進場載一次；後端排序契約為舊→新（初報→續報→結報）。
  const [storedReports, setStoredReports] = useState<SavedReport[]>([]);
  const [loadingReports, setLoadingReports] = useState(() => Boolean(id));

  useEffect(() => {
    if (!id) return;
    getStoredReports(id).then((list) => {
      setStoredReports(list);
      setLoadingReports(false);
    });
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
  const isFalseAlarm = event.verdict === 'false_alarm';
  const eventTypeLabel = getEventTypeLabel(event);
  const followUpCount = storedReports.filter((r) => r.form.reportType === '續報').length;

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">歷史事件詳情</h1>

      {/* 單欄置中：影片 → 事件資訊 → 通報歷程，依序堆疊。無任何推進操作按鈕。 */}
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
              loop
              playsInline
              onError={() => setVideoError(true)}
            />
          )}
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">事件資訊</h2>
          <InfoRow label="事件編號" value={event.id} />
          <InfoRow label="事件" value={eventTypeLabel} />
          <InfoRow label="事發地點" value={`${event.camera.zone}（${event.camera.name}）`} />
          <InfoRow label="事發時間" value={formatDateTime(event.occurred_at)} />
          <InfoRow label="事件狀態" value={<EventStatusBadge event={event} now={now} />} />
          <InfoRow
            label="續報期限"
            value={event.follow_up_deadline ? formatFullDate(event.follow_up_deadline) : '—'}
          />
          {followUpCount > 0 && <InfoRow label="已續報次數" value={`${followUpCount} 次`} />}
          {isFalseAlarm && <InfoRow label="備註" value={event.false_alarm_note ?? '—'} />}
        </div>

        {/* 通報歷程：同一筆事件的全部通報單（初報／續報／結報），逐筆折疊呈現。 */}
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <h2 className="mb-3 text-base font-semibold text-[var(--text-primary)]">
            通報歷程{storedReports.length > 0 && `（共 ${storedReports.length} 筆）`}
          </h2>
          {loadingReports ? (
            <p className="text-sm text-[var(--text-secondary)]">載入中…</p>
          ) : storedReports.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">此事件無通報單紀錄</p>
          ) : (
            <div className="flex flex-col gap-2">
              {storedReports.map((report, index) => (
                <ReportHistoryItem key={index} report={report} index={index} />
              ))}
            </div>
          )}
        </div>

        {/* 最新一筆通報單可跳列印／存 PDF 版面（唯讀，不含編輯）。 */}
        {storedReports.length > 0 && (
          <button
            type="button"
            onClick={() => navigate(`/reports/${event.id}/preview`)}
            className="w-full rounded-md border border-[var(--brand)] bg-transparent px-4 py-2 text-center text-sm font-medium text-[var(--brand)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
          >
            列印／存 PDF
          </button>
        )}
      </div>
    </div>
  );
}

export default HistoryEventDetail;

import { useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { ConfirmModal } from '../components/ConfirmModal';
import { CountdownTimer } from '../components/CountdownTimer';
import { DEMO_VIDEO_SRC } from '../components/FullScreenAlert';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { getEventTypeLabel } from '../utils/eventFlags';
import { REPORT_STAGES, REPORT_STAGE_LABEL } from '../types';
import type { CareEvent } from '../types';

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
  const { events, now, updateReportStage, restoreEvent } = useEvents();
  const [videoError, setVideoError] = useState(false);
  // 「已結報」需二次確認（結案並移入歷史）；初報／複報則即時更新。
  const [confirmFinal, setConfirmFinal] = useState(false);

  const event: CareEvent | undefined = events.find((e) => e.id === id);

  if (!event) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此事件</p>
      </div>
    );
  }

  const videoSrc = event.camera.stream_url ?? DEMO_VIDEO_SRC;
  // 誤報紀錄的事件：事件類型顯示誤報時選的類型，隱藏生成通報單與通報狀態，改提供「恢復事件」。
  const isFalseAlarm = event.verdict === 'false_alarm';
  const eventTypeLabel = getEventTypeLabel(event);

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件詳情</h1>

      {/* 單欄置中：影片 → 生成通報單按鈕 → 事件資訊 → 通報狀態，依序堆疊，寬度貼齊影片並置中。 */}
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        {/* 事發影片片段：維持 16:9 填滿（無灰邊）。 */}
        <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-[var(--bg-surface-2)]">
          {videoError ? (
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

        {!isFalseAlarm && (
          <button
            type="button"
            onClick={() => navigate(`/reports/${event.id}`)}
            className="w-full rounded-md bg-[var(--brand)] px-4 py-2 text-center text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2"
          >
            生成通報單
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
          {isFalseAlarm && <InfoRow label="備註" value={event.false_alarm_note ?? '—'} />}
        </div>

        {!isFalseAlarm && (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 className="text-base font-semibold text-[var(--text-primary)]">通報狀態</h2>
              <span className="text-sm text-[var(--text-secondary)]">
                目前：{event.report_stage ? REPORT_STAGE_LABEL[event.report_stage] : '尚未通報'}
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {REPORT_STAGES.map((stage) => {
                const active = event.report_stage === stage;
                return (
                  <button
                    key={stage}
                    type="button"
                    onClick={() =>
                      stage === 'final'
                        ? setConfirmFinal(true)
                        : updateReportStage(event.id, stage)
                    }
                    aria-pressed={active}
                    className={`rounded-md px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] focus-visible:ring-offset-2 ${
                      active
                        ? 'bg-[var(--brand)] text-white'
                        : 'border border-[var(--brand)] bg-transparent text-[var(--brand)] hover:bg-[var(--brand-soft)]'
                    }`}
                  >
                    {REPORT_STAGE_LABEL[stage]}
                  </button>
                );
              })}
            </div>
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

      {confirmFinal && (
        <ConfirmModal
          title="標記為結報"
          message="確定要標記為結報嗎？結報後事件將結案並移至歷史紀錄。"
          onConfirm={() => {
            updateReportStage(event.id, 'final');
            setConfirmFinal(false);
            navigate('/events');
          }}
          onCancel={() => setConfirmFinal(false)}
        />
      )}
    </div>
  );
}

export default EventDetail;

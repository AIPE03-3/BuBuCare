import { useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { DEMO_VIDEO_SRC } from '../components/FullScreenAlert';
import { EventStatusBadge } from '../components/EventStatusBadge';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { REPORT_STAGES, REPORT_STAGE_LABEL } from '../types';
import type { CareEvent } from '../types';

function BackButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate(-1)}
      className="self-start rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      ‹ 返回上一頁
    </button>
  );
}

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
  const { events, now, updateReportStage } = useEvents();
  const [videoError, setVideoError] = useState(false);

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

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件詳情</h1>

      {/* 桌機：影片左、資訊與按鈕右；窄螢幕（RWD）堆疊，資訊移到影片下方 */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start">
        {/* 事發影片片段：維持 16:9 填滿（無灰邊），以 max-w 控制尺寸使高度貼近右欄。 */}
        <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-[var(--bg-surface-2)] lg:max-w-2xl lg:flex-1">
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

        {/* 右側：事件資訊 + 通報狀態 */}
        <div className="flex w-full flex-col gap-4 lg:w-80 lg:shrink-0">
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
            <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">事件資訊</h2>
            <InfoRow label="事件編號" value={event.id} />
            <InfoRow label="事件" value="跌倒" />
            <InfoRow label="事發地點" value={`${event.camera.zone}（${event.camera.name}）`} />
            <InfoRow label="事發時間" value={formatDateTime(event.occurred_at)} />
            <InfoRow label="事件狀態" value={<EventStatusBadge event={event} now={now} />} />
          </div>

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
                    onClick={() => updateReportStage(event.id, stage)}
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
        </div>
      </div>
    </div>
  );
}

export default EventDetail;

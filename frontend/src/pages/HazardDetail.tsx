import { type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { useEvents } from '../hooks/eventsContext';
import { formatDateTime } from '../utils/time';
import { CAMERA_LABEL } from '../types';

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-3 text-sm last:border-b-0">
      <span className="shrink-0 text-[var(--text-secondary)]">{label}</span>
      <span className="min-w-0 text-right text-[var(--text-primary)]">{value}</span>
    </div>
  );
}

// 潛在危險詳情：畫面截圖、時間、物品類型；未排除時提供「已排除」鈕，點擊後移入歷史「已排除危險」。
export function HazardDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { hazardEvents, clearHazard } = useEvents();

  const hazard = hazardEvents.find((e) => e.id === id);

  if (!hazard) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">找不到此潛在危險紀錄</p>
      </div>
    );
  }

  const cleared = hazard.status === 'resolved';

  return (
    <div className="flex flex-col gap-4">
      <BackButton />
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">潛在危險詳情</h1>

      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        {/* 畫面截圖：灰色占位框（不接真串流，比照全案影像慣例） */}
        <div className="flex aspect-video w-full items-center justify-center rounded-xl bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
          {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
        </div>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-5 shadow-sm">
          <h2 className="mb-2 text-base font-semibold text-[var(--text-primary)]">危險資訊</h2>
          <InfoRow label="物品類型" value={hazard.hazard_object ?? '—'} />
          <InfoRow label="偵測時間" value={formatDateTime(hazard.occurred_at)} />
          <InfoRow label="偵測地點" value={`${hazard.camera.zone}（${hazard.camera.name}）`} />
          <InfoRow
            label="狀態"
            value={
              cleared ? (
                <span className="inline-flex items-center rounded-full bg-[var(--success-bg)] px-2 py-0.5 text-xs font-medium text-[var(--success)]">
                  已排除
                </span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-[var(--warning-bg)] px-2 py-0.5 text-xs font-medium text-[var(--warning)]">
                  待排除
                </span>
              )
            }
          />
        </div>

        {!cleared && (
          <button
            type="button"
            onClick={() => {
              clearHazard(hazard.id);
              navigate('/events');
            }}
            className="w-full rounded-md bg-[var(--success)] px-4 py-2 text-center text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--success)] focus-visible:ring-offset-2"
          >
            已排除
          </button>
        )}
      </div>
    </div>
  );
}

export default HazardDetail;

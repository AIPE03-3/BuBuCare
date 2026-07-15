import { useEffect, useMemo, useState } from 'react';
import { getDownloadableMedia } from '../api/mediaDownloads';
import { QuickToggle } from '../components/QuickToggle';
import { QuietFilterPills } from '../components/QuietFilterPills';
import { DownloadIcon, FlagIcon, ImageIcon, VideoClipIcon } from '../components/icons';
import { STATUS_LABEL } from '../types';
import type { DownloadableMedia } from '../types';

type StatusFilter = 'all' | 'resolved' | 'false_alarm';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'resolved', label: STATUS_LABEL.resolved },
  { value: 'false_alarm', label: '誤報' },
];

const ALL_ZONES_VALUE = 'all';
const ALL_ZONES_LABEL = '全部區域';

// 即將到期門檻（天）：與保存期限欄位的 --danger／--warning 顏色門檻一致，見 renderExpiry。
const EXPIRING_SOON_DAYS = 7;

const MEDIA_TYPE_ICON: Record<DownloadableMedia['media_type'], typeof VideoClipIcon> = {
  event_clip: VideoClipIcon,
  env_snapshot: ImageIcon,
};

const MEDIA_TYPE_LABEL: Record<DownloadableMedia['media_type'], string> = {
  event_clip: '事件影片',
  env_snapshot: '環境截圖',
};

function daysUntil(expiresAt: string, now: number): number {
  return Math.ceil((new Date(expiresAt).getTime() - now) / (24 * 60 * 60 * 1000));
}

function renderExpiry(media: DownloadableMedia, now: number) {
  if (media.is_expired) {
    return <span className="text-[var(--text-muted)]">已過期</span>;
  }
  const days = daysUntil(media.expires_at, now);
  const colorClass = days <= 3 ? 'text-[var(--danger)]' : days <= 7 ? 'text-[var(--warning)]' : 'text-[var(--text-secondary)]';
  return <span className={colorClass}>剩 {days} 天</span>;
}

function renderMediaTypeIcon(media: DownloadableMedia) {
  const Icon = MEDIA_TYPE_ICON[media.media_type];
  return <Icon aria-hidden="true" className="h-4 w-4 shrink-0 text-[var(--text-secondary)]" />;
}

function renderLocation(media: DownloadableMedia): string {
  const { camera } = media;
  // demo 資料不顯示樓層，格式固定「區域・攝影機」；樓層待有值時補（樓層・）前綴。
  return camera.floor ? `${camera.floor}・${camera.zone}・${camera.name}` : `${camera.zone}・${camera.name}`;
}

function renderStatus(media: DownloadableMedia) {
  if (media.media_type === 'env_snapshot') {
    return <span className="text-[var(--text-muted)]">—</span>;
  }
  const isFalseAlarm = media.verdict === 'false_alarm';
  const label = isFalseAlarm ? '誤報' : media.status ? STATUS_LABEL[media.status] : '—';
  const style = isFalseAlarm
    ? 'border border-[var(--offline)] text-[var(--offline)] bg-transparent'
    : 'border border-transparent bg-[var(--success-bg)] text-[var(--success)]';

  return (
    <div className="flex items-center gap-1.5">
      <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>{label}</span>
      {isFalseAlarm && media.false_alarm_type && (
        <span className="text-xs text-[var(--text-muted)]">{media.false_alarm_type}</span>
      )}
      {media.escalated && (
        <span title="曾升級">
          <FlagIcon aria-hidden="true" className="h-4 w-4 text-[var(--danger)]" />
        </span>
      )}
    </div>
  );
}

export function MediaDownloads() {
  const [items, setItems] = useState<DownloadableMedia[]>([]);
  const [zoneFilter, setZoneFilter] = useState<string>(ALL_ZONES_VALUE);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [expiringSoonOnly, setExpiringSoonOnly] = useState(false);
  const [hideExpired, setHideExpired] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [now] = useState(() => Date.now());

  useEffect(() => {
    getDownloadableMedia().then(setItems);
  }, []);

  const zones = useMemo(() => Array.from(new Set(items.map((m) => m.camera.zone))), [items]);

  const filtered = useMemo(() => {
    return items.filter((media) => {
      if (zoneFilter !== ALL_ZONES_VALUE && media.camera.zone !== zoneFilter) return false;
      if (statusFilter === 'resolved' && !(media.status === 'resolved' && media.verdict !== 'false_alarm')) return false;
      if (statusFilter === 'false_alarm' && media.verdict !== 'false_alarm') return false;
      if (expiringSoonOnly && (media.is_expired || daysUntil(media.expires_at, now) > EXPIRING_SOON_DAYS)) return false;
      if (hideExpired && media.is_expired) return false;
      return true;
    });
  }, [items, zoneFilter, statusFilter, expiringSoonOnly, hideExpired, now]);

  // 全選三態只計算「非已過期」的列，已過期列不可勾選、不列入計數。
  const selectableIds = useMemo(() => filtered.filter((m) => !m.is_expired).map((m) => m.id), [filtered]);
  const selectedCount = selectableIds.filter((id) => selectedIds.has(id)).length;
  const allSelected = selectableIds.length > 0 && selectedCount === selectableIds.length;
  const someSelected = selectedCount > 0 && !allSelected;

  function toggleOne(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelectedIds((prev) => {
      if (allSelected) return new Set();
      const next = new Set(prev);
      selectableIds.forEach((id) => next.add(id));
      return next;
    });
  }

  function handleDownloadSelected() {
    // 下載連結安全機制待後端提供（見 04_後端現況與規格落差.md H 段），本輪僅 demo 互動。
    console.info('[MediaDownloads] 下載已選取項目', Array.from(selectedIds));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-1">
            <select
              value={zoneFilter}
              onChange={(e) => setZoneFilter(e.target.value)}
              className="border-0 border-b border-transparent bg-transparent px-0 py-1 text-sm text-[var(--text-secondary)] transition-colors duration-150 focus:border-[var(--brand)] focus:outline-none"
            >
              <option value={ALL_ZONES_VALUE}>{ALL_ZONES_LABEL}</option>
              {zones.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </div>

          <QuietFilterPills options={STATUS_OPTIONS} value={statusFilter} onChange={setStatusFilter} />
        </div>

        <div className="flex flex-wrap items-center gap-4">
          <QuickToggle checked={expiringSoonOnly} onChange={setExpiringSoonOnly} label="只顯示即將到期" />
          <QuickToggle checked={hideExpired} onChange={setHideExpired} label="隱藏已過期" />
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-medium">
                <input
                  type="checkbox"
                  checked={allSelected}
                  ref={(el) => {
                    if (el) el.indeterminate = someSelected;
                  }}
                  onChange={toggleAll}
                  disabled={selectableIds.length === 0}
                  className="h-4 w-4 accent-[var(--brand)]"
                  aria-label="全選"
                />
              </th>
              <th className="px-3 py-2 font-medium">類型</th>
              <th className="px-3 py-2 font-medium">攝影機位置</th>
              <th className="px-3 py-2 font-medium">狀態</th>
              <th className="px-3 py-2 font-medium">保存期限</th>
              <th className="px-3 py-2 font-medium">下載</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((media) => (
              <tr
                key={media.id}
                className={`border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 ${
                  media.is_expired ? 'opacity-50' : ''
                }`}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(media.id)}
                    onChange={() => toggleOne(media.id)}
                    disabled={media.is_expired}
                    className="h-4 w-4 accent-[var(--brand)]"
                    aria-label={`選取 ${media.id}`}
                  />
                </td>
                <td className="px-3 py-2 text-[var(--text-primary)]">
                  <span className="inline-flex items-center gap-1.5">
                    {renderMediaTypeIcon(media)}
                    {MEDIA_TYPE_LABEL[media.media_type]}
                  </span>
                </td>
                <td className="px-3 py-2 text-[var(--text-primary)]">{renderLocation(media)}</td>
                <td className="px-3 py-2">{renderStatus(media)}</td>
                <td className="px-3 py-2">{renderExpiry(media, now)}</td>
                <td className="px-3 py-2">
                  {media.is_expired ? (
                    <span title="檔案已刪除" className="cursor-not-allowed">
                      <DownloadIcon aria-hidden="true" className="h-4 w-4 text-[var(--text-muted)]" />
                    </span>
                  ) : (
                    <a
                      href={media.download_url ?? undefined}
                      aria-label={`下載 ${media.id}`}
                      className="inline-flex text-[var(--brand)] transition-colors duration-150 hover:opacity-80"
                    >
                      <DownloadIcon aria-hidden="true" className="h-4 w-4" />
                    </a>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                  沒有符合篩選條件的影像片段
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-sm text-[var(--text-secondary)]">
          {selectedCount === 0 ? '尚未選取' : `已選取 ${selectedCount} 筆`}
        </span>
        <button
          type="button"
          onClick={handleDownloadSelected}
          disabled={selectedCount === 0}
          className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50"
        >
          下載已選取項目
        </button>
      </div>
    </div>
  );
}

export default MediaDownloads;

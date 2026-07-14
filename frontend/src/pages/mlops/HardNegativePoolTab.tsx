import { useEffect, useMemo, useState } from 'react';
import { getHardNegatives } from '../../api/hardNegatives';
import { ClipPlayerModal } from '../../components/ClipPlayerModal';
import { QuietFilterPills } from '../../components/QuietFilterPills';
import type { EnvHistoryRange, HardNegativeItem, HnpLabel } from '../../types';
import { formatDate, formatTime } from '../../utils/time';

const PAGE_SIZE = 10;

const LABEL_OPTIONS: HnpLabel[] = ['坐地', '伸展', '彎腰', '攙扶', '其他'];

type LabelFilter = 'all' | HnpLabel;

const RANGE_OPTIONS: { value: EnvHistoryRange; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'custom', label: '自訂' },
];

// 灰字空心外框標籤樣式，比照 StatusTag 的 FALSE_ALARM_STYLE（誤報／離線語意，見 CLAUDE.md 狀態標籤配色表）。
const HOLLOW_OFFLINE_STYLE = 'border border-[var(--offline)] text-[var(--offline)] bg-transparent';

function rangeToWindow(range: EnvHistoryRange, now: number, customFrom: string, customTo: string): { from: string; to: string } | null {
  const toIso = new Date(now).toISOString();
  if (range === 'today') return { from: new Date(now - 24 * 60 * 60 * 1000).toISOString(), to: toIso };
  if (range === '7d') return { from: new Date(now - 7 * 24 * 60 * 60 * 1000).toISOString(), to: toIso };
  if (range === '30d') return { from: new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString(), to: toIso };
  if (!customFrom || !customTo) return null;
  return { from: new Date(customFrom).toISOString(), to: new Date(customTo).toISOString() };
}

// 攝影機位置「區域・攝影機」格式；demo 不顯示樓層，樓層待有值時補前綴（比照 MediaDownloads.tsx 的 renderLocation）。
function renderLocation(item: HardNegativeItem): string {
  const { camera } = item;
  return camera.floor ? `${camera.floor}・${camera.zone}・${camera.name}` : `${camera.zone}・${camera.name}`;
}

export function HardNegativePoolTab() {
  const [dateFiltered, setDateFiltered] = useState<HardNegativeItem[]>([]);
  const [labelFilter, setLabelFilter] = useState<LabelFilter>('all');
  const [range, setRange] = useState<EnvHistoryRange>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [page, setPage] = useState(1);
  const [playingClip, setPlayingClip] = useState<string | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    const dateRange = rangeToWindow(range, now, customFrom, customTo) ?? undefined;
    getHardNegatives({ dateRange }).then(setDateFiltered);
  }, [range, customFrom, customTo, now]);

  function handleRangeChange(next: EnvHistoryRange) {
    setRange(next);
    setPage(1);
  }

  function handleLabelChange(next: LabelFilter) {
    setLabelFilter(next);
    setPage(1);
  }

  // 誤報類型下拉的每項計數：依「日期篩選後、類型篩選前」的清單自算，避免自己篩自己導致計數失真。
  const labelCounts = useMemo(() => {
    const counts = new Map<HnpLabel, number>();
    for (const item of dateFiltered) counts.set(item.label, (counts.get(item.label) ?? 0) + 1);
    return counts;
  }, [dateFiltered]);

  const labelPillOptions = useMemo(
    () => [
      { value: 'all' as LabelFilter, label: `全部類型 (${dateFiltered.length})` },
      ...LABEL_OPTIONS.map((label) => ({
        value: label as LabelFilter,
        label: `${label} (${labelCounts.get(label) ?? 0})`,
      })),
    ],
    [dateFiltered.length, labelCounts],
  );

  const items = useMemo(
    () => (labelFilter === 'all' ? dateFiltered : dateFiltered.filter((item) => item.label === labelFilter)),
    [dateFiltered, labelFilter],
  );

  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const pageItems = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="flex flex-col gap-4">
      {/* 篩選列 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <QuietFilterPills options={labelPillOptions} value={labelFilter} onChange={handleLabelChange} />
        </div>

        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => handleRangeChange(e.target.value as EnvHistoryRange)}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
          >
            {RANGE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          {range === 'custom' && (
            <>
              <input
                type="date"
                value={customFrom}
                onChange={(e) => {
                  setCustomFrom(e.target.value);
                  setPage(1);
                }}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
              />
              <span className="text-sm text-[var(--text-secondary)]">至</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => {
                  setCustomTo(e.target.value);
                  setPage(1);
                }}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
              />
            </>
          )}

          {/* 匯出全部：本輪 MVP 無接收端，先做視覺與語意，不接互動（見 00_專案總覽.md 動工決策）。 */}
          <button
            type="button"
            disabled
            title="後端資料飛輪管道尚未就緒"
            className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-50"
          >
            匯出全部
          </button>
        </div>
      </div>

      {/* 誤報清單表 */}
      <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-medium">攝影機位置</th>
              <th className="px-3 py-2 font-medium">誤報類型</th>
              <th className="px-3 py-2 font-medium">備註</th>
              <th className="px-3 py-2 font-medium">標記者・時間</th>
              <th className="px-3 py-2 font-medium">播放</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((item) => (
              <tr key={item.id} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                <td className="px-3 py-2 text-[var(--text-primary)]">{renderLocation(item)}</td>
                <td className="px-3 py-2">
                  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${HOLLOW_OFFLINE_STYLE}`}>
                    {item.label}
                  </span>
                </td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">{item.note ?? '—'}</td>
                <td className="px-3 py-2 text-[var(--text-primary)]">
                  <div>{item.labeled_by}</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    {formatDate(item.labeled_at)} {formatTime(item.labeled_at)}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setPlayingClip(item.clip_path)}
                    aria-label={`播放 ${item.id}`}
                    className="text-[var(--brand)] transition-colors duration-150 hover:underline"
                  >
                    ▶
                  </button>
                </td>
              </tr>
            ))}
            {pageItems.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                  查無符合篩選條件的誤報紀錄
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* 靜態頁碼分頁 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPage(p)}
              className={`rounded-md px-3 py-1 text-sm transition-colors duration-150 ${
                p === page
                  ? 'bg-[var(--brand)] text-white'
                  : 'border border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      )}

      {playingClip !== null && <ClipPlayerModal clipPath={playingClip} onClose={() => setPlayingClip(null)} />}
    </div>
  );
}

export default HardNegativePoolTab;

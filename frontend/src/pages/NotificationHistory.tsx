import { useEffect, useState } from 'react';
import { getNotificationRecordsWithEvents } from '../api/notifications';
import type { NotificationWithEvent } from '../api/notifications';
import { NotificationDetailModal } from '../components/NotificationDetailModal';
import { NotificationStatusTag } from '../components/NotificationStatusTag';
import { QuietFilterPills } from '../components/QuietFilterPills';
import { useAuth } from '../hooks/useAuth';
import type { NotificationChannel, NotificationStatus } from '../types';
import { CHANNEL_LABEL } from '../types';
import { formatDate, formatTime } from '../utils/time';

type StatusFilter = 'all' | NotificationStatus;
type DateRangeOption = 'today' | '7d' | '30d' | 'custom';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'delivered', label: '已送達' },
  { value: 'failed', label: '發送失敗' },
];

const CHANNEL_OPTIONS: { value: NotificationChannel; label: string }[] = (
  Object.keys(CHANNEL_LABEL) as NotificationChannel[]
).map((value) => ({ value, label: CHANNEL_LABEL[value] }));

const RANGE_OPTIONS: { value: DateRangeOption; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'custom', label: '自訂' },
];

const PAGE_SIZE = 10;

function rangeToDates(range: DateRangeOption, customFrom: string, customTo: string): { from?: string; to?: string } {
  const now = new Date();
  if (range === 'today') {
    const start = new Date(now);
    start.setHours(0, 0, 0, 0);
    return { from: start.toISOString(), to: now.toISOString() };
  }
  if (range === '7d') {
    return { from: new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString(), to: now.toISOString() };
  }
  if (range === '30d') {
    return { from: new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString(), to: now.toISOString() };
  }
  return {
    from: customFrom ? new Date(customFrom).toISOString() : undefined,
    to: customTo ? new Date(customTo).toISOString() : undefined,
  };
}

export function NotificationHistory() {
  const { role } = useAuth();
  const [records, setRecords] = useState<NotificationWithEvent[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
  const [channelFilter, setChannelFilter] = useState<NotificationChannel>('web_push');
  const [range, setRange] = useState<DateRangeOption>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [page, setPage] = useState(1);
  const [activeDetail, setActiveDetail] = useState<NotificationWithEvent | null>(null);

  useEffect(() => {
    getNotificationRecordsWithEvents().then(setRecords);
  }, []);

  // 通報紀錄僅 admin 可見；staff 若以其他方式觸發此元件（例如頁籤陣列被繞過），一律不渲染任何內容。
  if (role !== 'admin') return null;

  const { from, to } = rangeToDates(range, customFrom, customTo);

  const filtered = records.filter((record) => {
    if (statusFilter !== 'all' && record.status !== statusFilter) return false;
    if (record.channel !== channelFilter) return false;
    const sentAtMs = new Date(record.sent_at).getTime();
    if (from && sentAtMs < new Date(from).getTime()) return false;
    if (to && sentAtMs > new Date(to).getTime()) return false;
    return true;
  });

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  function handleStatusFilterChange(next: StatusFilter) {
    setStatusFilter(next);
    setPage(1);
  }

  function handleChannelFilterChange(next: NotificationChannel) {
    setChannelFilter(next);
    setPage(1);
  }

  function handleRangeChange(next: DateRangeOption) {
    setRange(next);
    setPage(1);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <QuietFilterPills options={STATUS_OPTIONS} value={statusFilter} onChange={handleStatusFilterChange} />
          <select
            value={channelFilter}
            onChange={(e) => handleChannelFilterChange(e.target.value as NotificationChannel)}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
          >
            {CHANNEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => handleRangeChange(e.target.value as DateRangeOption)}
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
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-medium">事件摘要</th>
              <th className="px-3 py-2 font-medium">發送管道</th>
              <th className="px-3 py-2 font-medium">發送時間</th>
              <th className="px-3 py-2 font-medium">發送狀態</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((record) => (
              <tr key={record.id} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                <td className="px-3 py-2">
                  {record.event ? (
                    <button
                      type="button"
                      onClick={() => setActiveDetail(record)}
                      className="text-[var(--brand)] underline underline-offset-2 transition-colors duration-150"
                    >
                      {record.event.camera.zone}・跌倒
                    </button>
                  ) : (
                    <span className="text-[var(--text-muted)]">－</span>
                  )}
                </td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">{CHANNEL_LABEL[record.channel]}</td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">
                  {formatDate(record.sent_at)} {formatTime(record.sent_at)}
                </td>
                <td className="px-3 py-2">
                  <NotificationStatusTag status={record.status} />
                </td>
              </tr>
            ))}
            {pageItems.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                  沒有符合篩選條件的通報紀錄
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

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

      {activeDetail?.event && (
        <NotificationDetailModal event={activeDetail.event} onClose={() => setActiveDetail(null)} />
      )}
    </div>
  );
}

export default NotificationHistory;

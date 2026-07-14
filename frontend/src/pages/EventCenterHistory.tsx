import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getEventHistoryStats, queryEventHistory } from '../api/events';
import { QuickToggle } from '../components/QuickToggle';
import { QuietFilterPills } from '../components/QuietFilterPills';
import { StatusTag } from '../components/StatusTag';
import type { CareEvent, EventHistoryStatPoint } from '../types';
import { hasEscalatedFlag } from '../utils/eventFlags';
import { resolveCssVar } from '../utils/cssVar';
import { formatTime } from '../utils/time';

// 歷史終態一律 resolved，篩選改依 verdict 區分真跌倒／誤報。
type VerdictFilter = 'all' | 'true_alarm' | 'false_alarm';
type DateRangeOption = 'today' | '7d' | '30d' | 'custom';

const VERDICT_LABEL: Record<'true_alarm' | 'false_alarm', string> = {
  true_alarm: '已結案',
  false_alarm: '誤報',
};

const STATUS_OPTIONS: { value: VerdictFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'true_alarm', label: VERDICT_LABEL.true_alarm },
  { value: 'false_alarm', label: VERDICT_LABEL.false_alarm },
];

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

export function EventCenterHistory() {
  const navigate = useNavigate();
  const [statusFilter, setStatusFilter] = useState<VerdictFilter>('all');
  const [escalatedOnly, setEscalatedOnly] = useState(false);
  const [range, setRange] = useState<DateRangeOption>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<CareEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<EventHistoryStatPoint[]>([]);
  const [colors] = useState(() => ({ true_alarm: resolveCssVar('--success'), false_alarm: resolveCssVar('--offline') }));
  const [now] = useState(() => Date.now());

  const { from, to } = useMemo(() => rangeToDates(range, customFrom, customTo), [range, customFrom, customTo]);

  useEffect(() => {
    getEventHistoryStats(30).then(setStats);
  }, []);

  function handleStatusFilterChange(next: VerdictFilter) {
    setStatusFilter(next);
    setPage(1);
  }

  function handleEscalatedOnlyChange(next: boolean) {
    setEscalatedOnly(next);
    setPage(1);
  }

  function handleRangeChange(next: DateRangeOption) {
    setRange(next);
    setPage(1);
  }

  function handleCustomFromChange(next: string) {
    setCustomFrom(next);
    setPage(1);
  }

  function handleCustomToChange(next: string) {
    setCustomTo(next);
    setPage(1);
  }

  useEffect(() => {
    queryEventHistory({
      verdict: statusFilter === 'all' ? undefined : statusFilter,
      escalatedOnly,
      from,
      to,
      page,
      pageSize: PAGE_SIZE,
    }).then((result) => {
      setItems(result.items);
      setTotal(result.total);
    });
  }, [statusFilter, escalatedOnly, from, to, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">近 30 天件數統計</h2>
        <div className="h-64 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={stats}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" tick={{ fontSize: 12 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 12 }} />
              <Tooltip />
              <Legend formatter={(value) => VERDICT_LABEL[value as 'true_alarm' | 'false_alarm']} />
              <Bar dataKey="true_alarm" stackId="a" fill={colors.true_alarm} name="true_alarm" />
              <Bar dataKey="false_alarm" stackId="a" fill={colors.false_alarm} name="false_alarm" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <QuietFilterPills options={STATUS_OPTIONS} value={statusFilter} onChange={handleStatusFilterChange} />
          <QuickToggle checked={escalatedOnly} onChange={handleEscalatedOnlyChange} label="只顯示曾升級" />
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
                onChange={(e) => handleCustomFromChange(e.target.value)}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
              />
              <span className="text-sm text-[var(--text-secondary)]">至</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => handleCustomToChange(e.target.value)}
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
              <th className="px-3 py-2 font-medium">地點・類型</th>
              <th className="px-3 py-2 font-medium">發生時間</th>
              <th className="px-3 py-2 font-medium">最終狀態</th>
              <th className="px-3 py-2 font-medium">曾升級</th>
              <th className="px-3 py-2 font-medium">信心分數</th>
              <th className="px-3 py-2 font-medium">處理耗時</th>
            </tr>
          </thead>
          <tbody>
            {items.map((event) => (
              <tr
                key={event.id}
                onClick={() => navigate(`/events/${event.id}`)}
                className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
              >
                <td className="px-3 py-2 text-[var(--text-primary)]">
                  {event.camera.zone}・{event.camera.name}
                </td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">{formatTime(event.occurred_at)}</td>
                <td className="px-3 py-2">
                  <StatusTag status={event.status} verdict={event.verdict} now={now} />
                </td>
                <td className="px-3 py-2">
                  {hasEscalatedFlag(event) && (
                    <span aria-hidden="true" title="事件曾升級並通知當日值班組長">
                      🚩
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">{event.confidence.toFixed(2)}</td>
                <td className="px-3 py-2 text-[var(--text-secondary)]">
                  {/* CareEvent 已無 resolved_at、RawEventPayload 亦無結案時間欄，暫顯「—」，待後端補結案時間欄再接。 */}
                  —
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                  沒有符合篩選條件的歷史事件
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
    </div>
  );
}

export default EventCenterHistory;

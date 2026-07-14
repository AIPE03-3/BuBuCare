import { useEffect, useMemo, useState } from 'react';
import { Dot, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getCameras } from '../api/cameras';
import { getEnvScoreHistory } from '../api/envScores';
import { EnvScoreLevelBadge } from '../components/EnvScoreLevelBadge';
import type { Camera, EnvHistoryRange, EnvSafetyScore } from '../types';
import { groupCamerasByZone } from '../utils/groupCamerasByZone';
import { getAggregationLabel, getGranularityMs, getOfflinePeriods } from '../utils/envOfflinePeriods';
import type { OfflinePeriod } from '../utils/envOfflinePeriods';
import { LEVEL_COLOR_VAR, LEVEL_TEXT_CLASS } from '../utils/envScore';
import { resolveCssVar } from '../utils/cssVar';
import { formatDate, formatTime } from '../utils/time';

// 危險閾值虛線沿用 EnvDangerCard/EnvScoreDetail 的 DANGER_THRESHOLD = 39（等級門檻 0-39 危險／40-69 警示），全案一致。
const DANGER_THRESHOLD = 39;
const PAGE_SIZE = 10;

const RANGE_OPTIONS: { value: EnvHistoryRange; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'custom', label: '自訂' },
];

function rangeToSpanMs(range: EnvHistoryRange, customFrom: string, customTo: string): number | undefined {
  if (range !== 'custom') return undefined;
  if (!customFrom || !customTo) return undefined;
  return new Date(customTo).getTime() - new Date(customFrom).getTime();
}

// ── 攝影機選擇器（安靜版、區域分組收合、排除 disabled）──────────────────────────
function CameraPicker({
  cameras,
  selectedId,
  onSelect,
}: {
  cameras: Camera[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  // 總覽層排除規則（03 檔 §8）：選擇器清單排除已停用（disabled）裝置；離線（offline）仍可查歷史故保留。
  const selectable = cameras.filter((c) => c.status !== 'disabled');
  const zones = groupCamerasByZone(selectable);
  const selected = cameras.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)] underline underline-offset-4 transition-colors duration-150"
      >
        {/* demo 樓層固定 1 樓，沿用 Camera.floor 一律不顯示規則，只呈現「區域・攝影機」。 */}
        {selected ? `${selected.zone}・${selected.name}` : '選擇攝影機'}
        <span aria-hidden="true" className="text-xs text-[var(--text-muted)]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute z-10 mt-2 max-h-80 w-56 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-2 shadow-sm">
          {zones.map((group) => (
            <div key={group.zone} className="mb-2 last:mb-0">
              <p className="px-2 py-1 text-xs font-medium text-[var(--text-muted)]">{group.zone}</p>
              {group.cameras.map((camera) => {
                const active = camera.id === selectedId;
                return (
                  <button
                    key={camera.id}
                    type="button"
                    onClick={() => {
                      onSelect(camera.id);
                      setOpen(false);
                    }}
                    className={`block w-full rounded-md px-2 py-1 text-left text-sm transition-colors duration-150 ${
                      active
                        ? 'font-medium text-[var(--text-primary)] underline underline-offset-4'
                        : 'text-[var(--text-secondary)]'
                    }`}
                  >
                    {camera.name}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── 等級徽章（表格用）：良好等實心底徽章沿用 EnvScoreLevelBadge；離線用灰字空心外框（狀態標籤配色規則）──
function OfflineBadge() {
  return (
    <span className="inline-flex items-center rounded-full border border-[var(--offline)] px-2 py-0.5 text-xs font-medium text-[var(--offline)]">
      離線
    </span>
  );
}

// 表格列：正常聚合點，或合併的離線區間列。
type TableRow =
  | { kind: 'score'; point: EnvSafetyScore; isReconnect: boolean }
  | { kind: 'offline'; period: OfflinePeriod };

// 將聚合序列與離線區間合併成依時間排序的表格列（離線段併成一列）。
function buildTableRows(points: EnvSafetyScore[], offlinePeriods: OfflinePeriod[]): TableRow[] {
  const reconnectAts = new Set(offlinePeriods.map((p) => p.to));
  const rows: TableRow[] = points.map((point) => ({
    kind: 'score',
    point,
    isReconnect: reconnectAts.has(point.assessed_at),
  }));
  // 在每個離線區間「恢復首筆」之前插入一列離線列。
  for (const period of offlinePeriods) {
    const idx = rows.findIndex((r) => r.kind === 'score' && r.point.assessed_at === period.to);
    if (idx >= 0) rows.splice(idx, 0, { kind: 'offline', period });
  }
  return rows;
}

// 自訂資料點：恢復連線首筆畫空心圓（白填底＋offline 外框，無前次可比較）；其餘依等級實心圓（顏色來源與等級徽章/分數欄一致）。
function renderScoreDot(reconnectAts: Set<string>) {
  return function ScoreDot(props: unknown) {
    const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: { assessed_at: string; grade: EnvSafetyScore['grade'] } };
    if (cx === undefined || cy === undefined || !payload) return <></>;
    if (reconnectAts.has(payload.assessed_at)) {
      return <Dot key={`rc-${cx}-${cy}`} cx={cx} cy={cy} r={4} fill={resolveCssVar('--bg-surface')} stroke={resolveCssVar('--offline')} strokeWidth={2} />;
    }
    return <Dot key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={3.5} fill={resolveCssVar(LEVEL_COLOR_VAR[payload.grade])} stroke="none" />;
  };
}

// 趨勢圖 hover tooltip：顯示評分時間、分數、等級；恢復連線首筆額外顯示「無前次可比較」。
function ChartTooltip({
  active,
  payload,
  reconnectAts,
}: {
  active?: boolean;
  payload?: { payload: { assessed_at: string; score: number; grade: EnvSafetyScore['grade'] } }[];
  reconnectAts: Set<string>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-xs shadow-sm">
      <p className="font-medium text-[var(--text-primary)]">
        {formatDate(point.assessed_at)} {formatTime(point.assessed_at)}
      </p>
      <p className="text-[var(--text-secondary)]">分數：{point.score}</p>
      <p className={LEVEL_TEXT_CLASS[point.grade]}>等級：{point.grade}</p>
      {reconnectAts.has(point.assessed_at) && <p className="text-[var(--offline)]">無前次可比較</p>}
    </div>
  );
}

// X 軸日期標籤去重：同一天只在該天第一個資料點顯示日期字串，其餘回傳空字串，適應不同聚合粒度（每小時/每日）。
function makeDedupedDateFormatter(labels: string[]) {
  const firstIndexOfLabel = new Map<string, number>();
  labels.forEach((label, i) => {
    if (!firstIndexOfLabel.has(label)) firstIndexOfLabel.set(label, i);
  });
  return function formatTick(label: string, index: number): string {
    return firstIndexOfLabel.get(label) === index ? label : '';
  };
}

export function EnvScoreHistory() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [range, setRange] = useState<EnvHistoryRange>('7d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [scores, setScores] = useState<EnvSafetyScore[]>([]);
  const [page, setPage] = useState(1);

  useEffect(() => {
    getCameras().then((all) => {
      setCameras(all);
      // 預設選第一台可選（非 disabled）裝置；優先選有歷史資料的離線 demo 台（走廊A・鏡頭3）。
      const preferred = all.find((c) => c.id === 3 && c.status !== 'disabled');
      const first = preferred ?? all.find((c) => c.status !== 'disabled');
      if (first) setSelectedId(first.id);
    });
  }, []);

  useEffect(() => {
    if (selectedId === null) return;
    const custom = range === 'custom' && customFrom && customTo ? { from: customFrom, to: customTo } : undefined;
    getEnvScoreHistory(selectedId, range, custom).then(setScores);
  }, [selectedId, range, customFrom, customTo]);

  // 篩選改變時回到第 1 頁；改在事件處理器而非 effect 內設 state，避免 effect 內連鎖 render。
  function handleSelectCamera(id: number) {
    setSelectedId(id);
    setPage(1);
  }
  function handleRangeChange(next: EnvHistoryRange) {
    setRange(next);
    setPage(1);
  }

  const spanMs = rangeToSpanMs(range, customFrom, customTo);
  const offlinePeriods = useMemo(
    () => getOfflinePeriods(scores, getGranularityMs(range, spanMs)),
    [scores, range, spanMs],
  );
  const reconnectAts = useMemo(() => new Set(offlinePeriods.map((p) => p.to)), [offlinePeriods]);

  // 圖表資料：加上 label（給 XAxis）與 grade（tooltip/資料點上色用），主線於離線區間自然斷開（連續點才連線）。
  const chartData = useMemo(
    () => scores.map((s) => ({ assessed_at: s.assessed_at, score: s.total_score, grade: s.grade, label: formatDate(s.assessed_at) })),
    [scores],
  );
  const dateTickFormatter = useMemo(
    () => makeDedupedDateFormatter(chartData.map((d) => d.label)),
    [chartData],
  );

  // 離線橋接虛線：每個離線區間取前後兩點，畫一條 offline 色虛線連接（不留空白斷開、不加文字框）。
  const bridgeSegments = useMemo(
    () =>
      offlinePeriods.map((period) => {
        const before = [...scores].reverse().find((s) => new Date(s.assessed_at).getTime() < new Date(period.from).getTime() + 1);
        const after = scores.find((s) => s.assessed_at === period.to);
        return before && after
          ? [
              { assessed_at: before.assessed_at, bridge: before.total_score, label: formatDate(before.assessed_at) },
              { assessed_at: after.assessed_at, bridge: after.total_score, label: formatDate(after.assessed_at) },
            ]
          : [];
      }),
    [offlinePeriods, scores],
  );

  // buildTableRows 依時間由舊到新合併離線列；表格顯示改「新到舊」，故合併完再反轉，離線合併邏輯不受影響。
  const tableRows = useMemo(() => [...buildTableRows(scores, offlinePeriods)].reverse(), [scores, offlinePeriods]);
  const totalPages = Math.max(1, Math.ceil(tableRows.length / PAGE_SIZE));
  const pageRows = tableRows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const selectedCamera = cameras.find((c) => c.id === selectedId) ?? null;

  return (
    <div className="flex flex-col gap-4">
      {/* 篩選區 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CameraPicker cameras={cameras} selectedId={selectedId} onSelect={handleSelectCamera} />

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
          <span className="text-xs text-[var(--text-muted)]">對應粒度：{getAggregationLabel(range, spanMs)}</span>
        </div>
      </div>

      {/* 評分趨勢圖 */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">評分趨勢</h2>
        {chartData.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--text-muted)]">此區間查無評分紀錄</p>
        ) : (
          <>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <ReferenceArea y1={0} y2={DANGER_THRESHOLD} fill={resolveCssVar('--danger-bg')} fillOpacity={0.5} />
                  <ReferenceLine y={DANGER_THRESHOLD} stroke={resolveCssVar('--danger')} strokeDasharray="4 4" />
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} interval="preserveStartEnd" tickFormatter={dateTickFormatter} />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                  <Tooltip content={<ChartTooltip reconnectAts={reconnectAts} />} />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke={resolveCssVar('--brand')}
                    strokeWidth={2}
                    dot={renderScoreDot(reconnectAts)}
                    connectNulls={false}
                    isAnimationActive={false}
                  />
                  {/* 離線橋接虛線：每段離線用一條 offline 色虛線連接前後點。 */}
                  {bridgeSegments.map((seg, i) =>
                    seg.length === 2 ? (
                      <ReferenceLine
                        key={`bridge-${i}`}
                        segment={[
                          { x: seg[0].label, y: seg[0].bridge ?? 0 },
                          { x: seg[1].label, y: seg[1].bridge ?? 0 },
                        ]}
                        stroke={resolveCssVar('--offline')}
                        strokeDasharray="5 4"
                        strokeWidth={2}
                      />
                    ) : null,
                  )}
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--success)]" />
                良好／注意
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--warning)]" />
                警示
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--danger)]" />
                危險
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-0 w-4 border-t-2 border-dashed border-[var(--offline)]" />
                離線期間（虛線連接）
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full border-2 border-[var(--offline)] bg-[var(--bg-surface)]" />
                恢復連線首筆（無前次可比較）
              </span>
            </div>
          </>
        )}
      </div>

      {/* 原始紀錄表：4 欄固定（評分時間／分數／等級／較前次變化） */}
      <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-medium">評分時間</th>
              <th className="px-3 py-2 font-medium">分數</th>
              <th className="px-3 py-2 font-medium">等級</th>
              <th className="px-3 py-2 font-medium">較前次變化</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((row) =>
              row.kind === 'score' ? (
                <tr key={`s-${row.point.assessed_at}`} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                  <td className="px-3 py-2 text-[var(--text-primary)]">
                    <div>
                      {formatDate(row.point.assessed_at)} {formatTime(row.point.assessed_at)}
                    </div>
                    {/* 裝置資訊不另開欄位，併入評分時間下方小字（03 檔 §8）。 */}
                    <div className="text-xs text-[var(--text-muted)]">{selectedCamera?.name ?? `裝置 ${row.point.device_id}`}</div>
                  </td>
                  {/* 分數欄顏色沿用 LEVEL_TEXT_CLASS（與等級欄同一份對照），不另寫第二套色彩邏輯。 */}
                  <td className={`px-3 py-2 font-medium ${LEVEL_TEXT_CLASS[row.point.grade]}`}>{row.point.total_score}</td>
                  <td className="px-3 py-2">
                    <EnvScoreLevelBadge level={row.point.grade} />
                  </td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">
                    {row.point.score_drop === null
                      ? '—'
                      : row.point.score_drop === 0
                        ? '±0'
                        : row.point.score_drop > 0
                          ? `-${row.point.score_drop}`
                          : `+${Math.abs(row.point.score_drop)}`}
                  </td>
                </tr>
              ) : (
                <tr key={`o-${row.period.from}`} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                  <td className="px-3 py-2 text-[var(--text-secondary)]">
                    <div>
                      {formatDate(row.period.from)} {formatTime(row.period.from)}－{formatDate(row.period.to)} {formatTime(row.period.to)}
                    </div>
                    <div className="text-xs text-[var(--text-muted)]">{selectedCamera?.name ?? ''}</div>
                  </td>
                  <td className="px-3 py-2 font-medium text-[var(--offline)]">—</td>
                  <td className="px-3 py-2">
                    <OfflineBadge />
                  </td>
                  <td className="px-3 py-2 text-[var(--text-muted)]">—</td>
                </tr>
              ),
            )}
            {pageRows.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-sm text-[var(--text-muted)]">
                  此區間查無評分紀錄
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
    </div>
  );
}

export default EnvScoreHistory;

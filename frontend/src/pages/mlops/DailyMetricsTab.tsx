import { useEffect, useMemo, useState } from 'react';
import { Dot, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getCameras } from '../../api/cameras';
import { getDailyMetrics } from '../../api/mlops';
import { CameraPickerWithAll } from '../../components/CameraPickerWithAll';
import { KpiCard } from '../../components/KpiCard';
import type { Camera, EnvHistoryRange, ModelDailyMetric } from '../../types';
import { resolveCssVar } from '../../utils/cssVar';
import { formatDate } from '../../utils/time';

const RANGE_OPTIONS: { value: EnvHistoryRange; label: string }[] = [
  { value: 'today', label: '今天' },
  { value: '7d', label: '近 7 天' },
  { value: '30d', label: '近 30 天' },
  { value: 'custom', label: '自訂' },
];

// ⚠ 待確認：誤報數分級門檻為前端暫定值，尚未經組長／後端確認（見 00_專案總覽.md 2026-07-13 動工定案）。
const FP_COLOR_THRESHOLDS = { low: 2, mid: 5 } as const;

function fpColorVar(count: number): string {
  if (count <= FP_COLOR_THRESHOLDS.low) return '--success';
  if (count <= FP_COLOR_THRESHOLDS.mid) return '--warning';
  return '--danger';
}

function renderFpDot(props: unknown) {
  const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: { false_positive_count: number } };
  if (cx === undefined || cy === undefined || !payload) return <></>;
  return <Dot key={`fp-${cx}-${cy}`} cx={cx} cy={cy} r={3.5} fill={resolveCssVar(fpColorVar(payload.false_positive_count))} stroke="none" />;
}

function ChartTooltip({ active, payload }: { active?: boolean; payload?: { payload: { date: string; false_positive_count: number } }[] }) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-xs shadow-sm">
      <p className="font-medium text-[var(--text-primary)]">{formatDate(point.date)}</p>
      <p className="text-[var(--text-secondary)]">誤報數：{point.false_positive_count}</p>
    </div>
  );
}

const CHART_TITLE: Record<EnvHistoryRange, string> = {
  today: '今日誤報數',
  '7d': '近 7 天誤報數趨勢',
  '30d': '近 30 天誤報數趨勢',
  custom: '自訂區間誤報數趨勢',
};

export function DailyMetricsTab() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [range, setRange] = useState<EnvHistoryRange>('30d');
  const [customFrom, setCustomFrom] = useState('');
  const [customTo, setCustomTo] = useState('');
  const [metrics, setMetrics] = useState<ModelDailyMetric[]>([]);

  useEffect(() => {
    getCameras().then(setCameras);
  }, []);

  // 篩選列（日期區間／攝影機）同時驅動 KPI 卡與趨勢圖，兩者共用同一份資料，圖表隨篩選區間變化。
  useEffect(() => {
    getDailyMetrics({ range, deviceId: selectedId, customFrom, customTo }).then(setMetrics);
  }, [range, selectedId, customFrom, customTo]);

  const latest = metrics[metrics.length - 1] ?? null;

  const chartData = useMemo(
    () => metrics.map((m) => ({ date: m.date, false_positive_count: m.false_positive_count, label: formatDate(m.date) })),
    [metrics],
  );

  return (
    <div className="flex flex-col gap-4">
      {/* 篩選列 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <CameraPickerWithAll cameras={cameras} selectedId={selectedId} onSelect={setSelectedId} />

        <div className="flex items-center gap-2">
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as EnvHistoryRange)}
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
                onChange={(e) => setCustomFrom(e.target.value)}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
              />
              <span className="text-sm text-[var(--text-secondary)]">至</span>
              <input
                type="date"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
              />
            </>
          )}
        </div>
      </div>

      {/* KPI 卡 ×3，沿用首頁 KpiCard 元件樣式 */}
      {latest ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <KpiCard label="今日誤報數（FP/Day）" value={String(latest.false_positive_count)} />
          <KpiCard label="YOLO 信心分數均值" value={`${Math.round(latest.avg_confidence * 100)}%`} />
          <KpiCard label="VLM 推翻率" value={`${Math.round(latest.vlm_override_rate * 100)}%`} />
        </div>
      ) : (
        <p className="text-sm text-[var(--text-muted)]">此區間查無效能指標紀錄</p>
      )}

      {/* 誤報數趨勢圖，隨篩選列的日期區間變化 */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">{CHART_TITLE[range]}</h2>
        {chartData.length === 0 ? (
          <p className="py-8 text-center text-sm text-[var(--text-muted)]">此區間查無效能指標紀錄</p>
        ) : (
          <>
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <XAxis dataKey="label" tick={{ fontSize: 12 }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line
                    type="monotone"
                    dataKey="false_positive_count"
                    stroke={resolveCssVar('--brand')}
                    strokeWidth={2}
                    dot={renderFpDot}
                    isAnimationActive={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-[var(--text-muted)]">
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--success)]" />
                0–2 筆
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--warning)]" />
                3–5 筆
              </span>
              <span className="flex items-center gap-1">
                <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--danger)]" />
                6 筆以上
              </span>
            </div>
            <p className="mt-2 text-xs text-[var(--text-muted)]">
              色點依當日誤報數分級上色：0–2 綠／3–5 橙／6＋ 紅；門檻為前端暫定值，尚待組長／後端確認後調整。
            </p>
          </>
        )}
      </div>
    </div>
  );
}

export default DailyMetricsTab;

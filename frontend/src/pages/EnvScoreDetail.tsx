import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Dot, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import { getEnvScoreDetail } from '../api/envScores';
import type { EnvScoreAlert } from '../api/envScores';
import { EnvScoreLevelBadge } from '../components/EnvScoreLevelBadge';
import type { EnvDimensionScore, EnvScore, EnvScoreLevel } from '../types';
import { getEnvScoreLevel } from '../utils/envScore';
import { resolveCssVar } from '../utils/cssVar';
import { formatDate, formatTime } from '../utils/time';

const DANGER_THRESHOLD = 39;

type DetailData = EnvScore & { history: { date: string; score: number }[]; alerts: EnvScoreAlert[] };

const DIMENSION_LABEL: Record<'floor' | 'pathway' | 'hazard' | 'lighting', string> = {
  floor: '地面地板',
  pathway: '通道暢通性',
  hazard: '潛在危險物品',
  lighting: '照明條件',
};

const LEVEL_BAR_CLASS: Record<EnvScoreLevel, string> = {
  良好: 'bg-[var(--success)]',
  注意: 'bg-[var(--brand)]',
  警示: 'bg-[var(--warning)]',
  危險: 'bg-[var(--danger)]',
};

// 每日色點簡化為三色（正常/警示/危險），避免詳情頁認知負擔過重（不用四色良好/注意/警示/危險）。
type DotLevel = '正常' | '警示' | '危險';

function toDotLevel(score: number): DotLevel {
  const level = getEnvScoreLevel(score);
  if (level === '良好' || level === '注意') return '正常';
  if (level === '警示') return '警示';
  return '危險';
}

function BackButton() {
  const navigate = useNavigate();
  return (
    <button
      type="button"
      onClick={() => navigate('/environment')}
      className="self-start rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150"
    >
      ‹ 返回總覽
    </button>
  );
}

function DimensionBar({ dimensionKey, dimension }: { dimensionKey: keyof typeof DIMENSION_LABEL; dimension: EnvDimensionScore }) {
  const percent = (dimension.score / dimension.max) * 100;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-[var(--text-primary)]">{DIMENSION_LABEL[dimensionKey]}</span>
        <span className="text-[var(--text-secondary)]">
          {dimension.score}/{dimension.max}・{dimension.level}
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--bg-surface-2)]">
        <div className={`h-full rounded-full ${LEVEL_BAR_CLASS[dimension.level]}`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

function renderTrendDot(props: unknown) {
  const { cx, cy, payload } = props as { cx?: number; cy?: number; payload?: { score: number } };
  if (cx === undefined || cy === undefined || !payload) return <></>;
  const dotLevel = toDotLevel(payload.score);
  const color =
    dotLevel === '正常' ? resolveCssVar('--success') : dotLevel === '警示' ? resolveCssVar('--warning') : resolveCssVar('--danger');
  return <Dot key={`dot-${cx}-${cy}`} cx={cx} cy={cy} r={4} fill={color} stroke="none" />;
}

export function EnvScoreDetail() {
  const { scoreId } = useParams<{ scoreId: string }>();
  const [data, setData] = useState<DetailData | null | undefined>(undefined);

  useEffect(() => {
    if (!scoreId) return;
    getEnvScoreDetail(scoreId).then(setData);
  }, [scoreId]);

  if (data === undefined) {
    return <p className="text-sm text-[var(--text-muted)]">載入中…</p>;
  }

  if (data === null) {
    return (
      <div className="flex flex-col gap-4">
        <BackButton />
        <p className="text-sm text-[var(--text-muted)]">找不到這筆評分資料</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <BackButton />

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">
            {data.camera.zone}・{data.camera.name}
          </h1>
          {data.level && <EnvScoreLevelBadge level={data.level} />}
          {data.total_score !== null && (
            <span className="text-2xl font-semibold text-[var(--text-primary)]">{data.total_score}／100</span>
          )}
        </div>
        <p className="text-sm text-[var(--text-secondary)]">最後更新 {formatTime(data.assessed_at)}</p>
      </div>

      {data.history.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">評分趨勢（近 7 日）</h2>
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.history}>
                <ReferenceArea y1={0} y2={DANGER_THRESHOLD} fill={resolveCssVar('--danger-bg')} fillOpacity={0.5} />
                <ReferenceLine y={DANGER_THRESHOLD} stroke={resolveCssVar('--danger')} strokeDasharray="4 4" />
                <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 12 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="score" stroke={resolveCssVar('--brand')} strokeWidth={2} dot={renderTrendDot} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 flex items-center gap-4 text-xs text-[var(--text-muted)]">
            <span className="flex items-center gap-1">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--success)]" />
              正常
            </span>
            <span className="flex items-center gap-1">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--warning)]" />
              警示
            </span>
            <span className="flex items-center gap-1">
              <span aria-hidden="true" className="h-2 w-2 rounded-full bg-[var(--danger)]" />
              危險
            </span>
          </div>
        </div>
      )}

      {data.overall_description && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">整體描述</h2>
          <p className="text-sm text-[var(--text-secondary)]">{data.overall_description}</p>
        </div>
      )}

      {data.risk_factors.length > 0 && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="mb-2 text-sm font-medium text-[var(--text-primary)]">風險因子</h2>
          <div className="flex flex-wrap gap-2">
            {data.risk_factors.map((factor) => (
              <span
                key={factor}
                className="inline-flex items-center rounded-full bg-[var(--warning-bg)] px-3 py-1 text-xs font-medium text-[var(--warning)]"
              >
                {factor}
              </span>
            ))}
          </div>
        </div>
      )}

      {data.dimensions && (
        <div className="flex flex-col gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="text-sm font-medium text-[var(--text-primary)]">評分標準（四向度分析）</h2>
          <DimensionBar dimensionKey="floor" dimension={data.dimensions.floor} />
          <DimensionBar dimensionKey="pathway" dimension={data.dimensions.pathway} />
          <DimensionBar dimensionKey="hazard" dimension={data.dimensions.hazard} />
          <DimensionBar dimensionKey="lighting" dimension={data.dimensions.lighting} />
        </div>
      )}

      {data.alerts.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
          <h2 className="bg-[var(--bg-surface)] px-4 pt-4 text-sm font-medium text-[var(--text-primary)]">異常提醒紀錄</h2>
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
              <tr>
                <th className="px-3 py-2 font-medium">日期</th>
                <th className="px-3 py-2 font-medium">分數</th>
                <th className="px-3 py-2 font-medium">下跌幅度</th>
              </tr>
            </thead>
            <tbody>
              {data.alerts.map((alert) => (
                <tr key={alert.date} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                  <td className="px-3 py-2 text-[var(--text-primary)]">{formatDate(alert.date)}</td>
                  <td className="px-3 py-2 text-[var(--text-secondary)]">{alert.score}</td>
                  <td className="px-3 py-2 text-[var(--danger)]">-{alert.drop}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default EnvScoreDetail;

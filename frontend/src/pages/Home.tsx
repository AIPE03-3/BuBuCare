import { useEffect, useState } from 'react';
import { getKpiSummary } from '../api/kpi';
import { ActionRequiredCard } from '../components/ActionRequiredCard';
import { InProgressRow } from '../components/InProgressRow';
import { ResolvedRow } from '../components/ResolvedRow';
import { JudgingBadge } from '../components/JudgingBadge';
import { KpiCard } from '../components/KpiCard';
import { useEvents } from '../hooks/eventsContext';
import { groupEventsForHome } from '../utils/groupEventsForHome';
import type { KpiSummary } from '../types';

export function Home() {
  const [kpi, setKpi] = useState<KpiSummary | null>(null);
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const { events, now, handleLoadMore, handleAcknowledgeEvent, lastAckedId, clearLastAckedId } = useEvents();

  useEffect(() => {
    getKpiSummary().then(setKpi);
  }, []);

  useEffect(() => {
    if (!lastAckedId) return;
    const id = lastAckedId;
    const timer = setTimeout(() => {
      clearLastAckedId();
      setHighlightedId(id);
      document.getElementById(`event-card-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 0);
    return () => clearTimeout(timer);
  }, [lastAckedId, clearLastAckedId]);

  useEffect(() => {
    if (!highlightedId) return;
    const timer = setTimeout(() => setHighlightedId(null), 5000);
    return () => clearTimeout(timer);
  }, [highlightedId]);

  const groups = groupEventsForHome(events);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">首頁儀表版</h1>
        <div className="flex items-center gap-3">
          <p className="text-sm text-[var(--text-secondary)]">即時同步中</p>
          <JudgingBadge />
        </div>
      </div>

      {kpi && (
        <div className="grid grid-cols-4 gap-4">
          <KpiCard label="待處理事件" value={String(kpi.pending_events)} />
          <KpiCard label="今日誤報率" value={`${kpi.false_positive_rate}%`} />
          <KpiCard
            label="環境安全平均分"
            value={String(kpi.env_score_avg)}
            tone={kpi.env_score_avg < kpi.env_score_threshold ? 'danger' : 'default'}
          />
          <KpiCard
            label="MLOps 健康度"
            value={`${kpi.hnp_count} / ${kpi.hnp_threshold}`}
            subLabel="Hard Negative Pool 累積量"
            tone={kpi.hnp_count >= kpi.hnp_threshold ? 'warning' : 'default'}
          />
        </div>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">需要行動</h2>
        <div className="flex flex-col gap-3">
          {groups.needsAction.map((event) => (
            <div
              key={event.id}
              id={`event-card-${event.id}`}
              className={`rounded-xl transition-colors duration-150 ${
                event.id === highlightedId ? 'bg-[var(--brand-soft)]' : ''
              }`}
            >
              <ActionRequiredCard event={event} now={now} onAcknowledge={handleAcknowledgeEvent} />
            </div>
          ))}
          {groups.needsAction.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">目前沒有需要立即接手的事件</p>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">處理中</h2>
        <div className="flex flex-col gap-2">
          {groups.inProgress.map((event) => (
            <div
              key={event.id}
              id={`event-card-${event.id}`}
              className={`rounded-lg transition-colors duration-150 ${
                event.id === highlightedId ? 'bg-[var(--brand-soft)]' : ''
              }`}
            >
              <InProgressRow event={event} now={now} />
            </div>
          ))}
          {groups.inProgress.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">目前沒有處理中的事件</p>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">今日已結案</h2>
        <div className="flex flex-col gap-1">
          {groups.resolvedToday.map((event) => (
            <ResolvedRow key={event.id} event={event} />
          ))}
        </div>
        <p className="text-xs text-[var(--text-muted)]">今日另有 {groups.suppressedTodayCount} 筆誤報</p>
      </section>

      <button
        type="button"
        onClick={handleLoadMore}
        className="self-start rounded-md border border-[var(--brand)] bg-transparent px-4 py-2 text-sm text-[var(--brand)] transition-colors duration-150"
      >
        載入更多
      </button>
    </div>
  );
}

export default Home;

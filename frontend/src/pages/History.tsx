import { useState } from 'react';
import { EventHistoryList } from './EventHistoryList';
import { FalseAlarmHistoryList } from './FalseAlarmHistoryList';
import { HazardList } from '../components/HazardList';
import { useEvents } from '../hooks/eventsContext';

type HistoryTab = 'events' | 'falseAlarms' | 'clearedHazards';

const TABS: { value: HistoryTab; label: string }[] = [
  { value: 'events', label: '已結報事件' },
  { value: 'falseAlarms', label: '誤報紀錄' },
  { value: 'clearedHazards', label: '已排除危險' },
];

export function History() {
  const [tab, setTab] = useState<HistoryTab>('events');
  const { hazardEvents } = useEvents();
  // 已排除危險：hazard 事件中已標記 resolved 者。
  const clearedHazards = hazardEvents.filter((e) => e.status === 'resolved');

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">歷史紀錄</h1>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={`px-4 py-2 text-sm transition-colors duration-150 ${
              tab === t.value
                ? 'border-b-2 border-[var(--brand)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'events' && <EventHistoryList />}
      {tab === 'falseAlarms' && <FalseAlarmHistoryList />}
      {tab === 'clearedHazards' && (
        <HazardList hazards={clearedHazards} emptyMessage="尚無已排除危險" />
      )}
    </div>
  );
}

export default History;

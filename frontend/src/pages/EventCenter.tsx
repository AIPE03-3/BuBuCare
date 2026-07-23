import { useSearchParams } from 'react-router-dom';
import { EventCenterUnresolved } from './EventCenterUnresolved';
import { HazardList } from '../components/HazardList';
import { useEvents } from '../hooks/eventsContext';

type EventCenterTab = 'events' | 'hazards';

const TABS: { value: EventCenterTab; label: string }[] = [
  { value: 'events', label: '事件' },
  { value: 'hazards', label: '潛在危險' },
];

export function EventCenter() {
  // 分頁走網址參數（?tab=hazards），讓外部連結（如首頁「排除危險」鈕）可直接深連到指定分頁。
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: EventCenterTab = searchParams.get('tab') === 'hazards' ? 'hazards' : 'events';
  const { hazardEvents } = useEvents();
  // 潛在危險頁只列未排除者；已排除移入歷史「已排除危險」頁。
  const activeHazards = hazardEvents.filter((e) => e.status !== 'resolved');

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件中心</h1>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setSearchParams(t.value === 'events' ? {} : { tab: t.value })}
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

      {tab === 'events' && <EventCenterUnresolved showPending showAssignee />}
      {tab === 'hazards' && (
        <HazardList hazards={activeHazards} emptyMessage="目前沒有潛在危險" />
      )}
    </div>
  );
}

export default EventCenter;

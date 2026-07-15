import { useState } from 'react';
import { EventCenterHistory } from './EventCenterHistory';
import { EventCenterUnresolved } from './EventCenterUnresolved';

type EventCenterMode = 'unresolved' | 'history';

const MODE_TABS: { value: EventCenterMode; label: string }[] = [
  { value: 'unresolved', label: '未結案' },
  { value: 'history', label: '歷史查詢' },
];

export function EventCenter() {
  const [mode, setMode] = useState<EventCenterMode>('unresolved');

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件中心</h1>
      </div>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {MODE_TABS.map((tab) => (
          <button
            key={tab.value}
            type="button"
            onClick={() => setMode(tab.value)}
            className={`px-4 py-2 text-sm transition-colors duration-150 ${
              mode === tab.value
                ? 'border-b-2 border-[var(--brand)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {mode === 'unresolved' ? <EventCenterUnresolved /> : <EventCenterHistory />}
    </div>
  );
}

export default EventCenter;

import { useState } from 'react';
import { EventCard } from '../components/EventCard';
import { FilterChips } from '../components/FilterChips';
import { NewEventBanner } from '../components/NewEventBanner';
import { useEvents } from '../hooks/eventsContext';
import { EVENT_CENTER_LIVE_FILTERS } from '../types';
import type { EventFilter } from '../types';

const LIVE_STATUSES = ['in_progress', 'resolved'] as const;

export function EventCenterLive() {
  const [filter, setFilter] = useState<EventFilter>('all');
  const { events, now, incomingEvent, mergeIncomingEvent, handleLoadMore, handleAcknowledgeEvent, lastAckedId } =
    useEvents();

  const visibleEvents = events.filter((event) => LIVE_STATUSES.includes(event.status as (typeof LIVE_STATUSES)[number]));
  const filteredEvents =
    filter === 'all' ? visibleEvents : visibleEvents.filter((event) => event.status === filter);

  return (
    <div className="flex flex-col gap-4">
      {incomingEvent && <NewEventBanner onClick={mergeIncomingEvent} />}

      <FilterChips value={filter} onChange={setFilter} options={EVENT_CENTER_LIVE_FILTERS} />

      <div className="flex flex-col gap-3">
        {filteredEvents.map((event) => (
          <EventCard
            key={event.id}
            event={event}
            now={now}
            highlighted={event.id === lastAckedId}
            onAcknowledge={handleAcknowledgeEvent}
          />
        ))}
        {filteredEvents.length === 0 && (
          <p className="text-sm text-[var(--text-muted)]">目前沒有正在處理或今日已完成的事件</p>
        )}
      </div>

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

export default EventCenterLive;

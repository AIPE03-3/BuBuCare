import { EventCenterUnresolved } from './EventCenterUnresolved';

export function EventCenter() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">事件中心</h1>
      <EventCenterUnresolved />
    </div>
  );
}

export default EventCenter;

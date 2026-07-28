import { ResponsiveEventList, type EventListColumn } from './ResponsiveEventList';
import { formatDateTime } from '../utils/time';
import { HAZARD_OBJECT_LABEL } from '../types';
import type { CareEvent } from '../types';

// 潛在危險清單：事件中心「潛在危險」頁與歷史「已排除危險」頁共用同一版型，
// 差異只在傳入的資料（未排除／已排除）與空狀態文字。點列進入潛在危險詳情。
const columns: EventListColumn[] = [
  {
    key: 'time',
    header: '偵測時間',
    cell: (event) => (
      <span className="text-[var(--text-secondary)]">{formatDateTime(event.occurred_at)}</span>
    ),
  },
  {
    key: 'location',
    header: '偵測地點',
    cell: (event) => (
      <span className="text-[var(--text-primary)]">
        {event.camera.zone}（{event.camera.name}）
      </span>
    ),
  },
  {
    key: 'object',
    header: '物品類型',
    cell: (event) => (
      <span className="text-[var(--text-primary)]">
        {event.hazard_object ? HAZARD_OBJECT_LABEL[event.hazard_object] : '—'}
      </span>
    ),
  },
];

export function HazardList({
  hazards,
  emptyMessage,
}: {
  hazards: CareEvent[];
  emptyMessage: string;
}) {
  return (
    <ResponsiveEventList
      events={hazards}
      columns={columns}
      getRowHref={(event) => `/hazards/${event.id}`}
      emptyMessage={emptyMessage}
    />
  );
}

export default HazardList;

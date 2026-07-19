import { EventTable } from '../components/EventTable';
import { useEvents } from '../hooks/eventsContext';

// 已結報事件清單：status === 'resolved' 且非誤報。
// 事件在詳情頁點「已結報」後轉 resolved，即由事件中心（未結案）移入此處；誤報獨立於「誤報紀錄」分頁顯示。
export function EventHistoryList() {
  const { events } = useEvents();
  const resolved = events.filter(
    (event) => event.status === 'resolved' && event.verdict !== 'false_alarm',
  );

  return <EventTable events={resolved} emptyMessage="尚無已結案事件" />;
}

export default EventHistoryList;

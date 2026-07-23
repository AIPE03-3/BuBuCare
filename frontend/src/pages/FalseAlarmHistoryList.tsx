import { EventTable } from '../components/EventTable';
import { useEvents } from '../hooks/eventsContext';

// 誤報紀錄清單：verdict === 'false_alarm' 的事件（於全螢幕警示標記「誤報」後產生）。
export function FalseAlarmHistoryList() {
  const { events } = useEvents();
  const falseAlarms = events.filter((event) => event.verdict === 'false_alarm');

  // 誤報詳情同樣導向唯讀歷史詳情 /history/:id（誤報通常無通報單，歷程區塊顯示空狀態）。
  return (
    <EventTable
      events={falseAlarms}
      emptyMessage="尚無誤報紀錄"
      getRowHref={(event) => `/history/${event.id}`}
    />
  );
}

export default FalseAlarmHistoryList;

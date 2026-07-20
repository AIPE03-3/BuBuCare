import { EventTable } from '../components/EventTable';
import { useEvents } from '../hooks/eventsContext';

// 誤報紀錄清單：verdict === 'false_alarm' 的事件（於全螢幕警示標記「誤報」後產生）。
export function FalseAlarmHistoryList() {
  const { events } = useEvents();
  const falseAlarms = events.filter((event) => event.verdict === 'false_alarm');

  return <EventTable events={falseAlarms} emptyMessage="尚無誤報紀錄" />;
}

export default FalseAlarmHistoryList;

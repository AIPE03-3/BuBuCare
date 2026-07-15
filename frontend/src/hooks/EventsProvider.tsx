import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { getEvents, submitEventFeedback } from '../api/events';
import { FullScreenAlert } from '../components/FullScreenAlert';
import type { CareEvent, FalseReportLabel, ReportStage } from '../types';
import { EventsContext, type EventsContextValue } from './eventsContext';
import { useAuth } from './useAuth';
import { useEventSocket } from './useEventSocket';

const PAGE_SIZE = 3;
// 首頁「未結案事件」需一次顯示所有未結案事件、不分頁，故初始載入直接抓完全部 mock 資料；
// 「載入更多」（事件中心即時頁使用）仍維持每次 PAGE_SIZE 筆的漸進載入。
const INITIAL_LOAD_SIZE = 200;
const TICK_INTERVAL_MS = 1000;
const ACK_TOAST_DURATION_MS = 10000;

export function EventsProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [confirmedAlerts, setConfirmedAlerts] = useState<CareEvent[]>([]);
  const [lastAckedId, setLastAckedId] = useState<string | null>(null);
  const [ackToastEvent, setAckToastEvent] = useState<CareEvent | null>(null);
  const [lastAckedEvent, setLastAckedEvent] = useState<CareEvent | null>(null);

  const ackToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const preAckSnapshotRef = useRef<Map<string, CareEvent>>(new Map());

  // 初始清單目前仍走 mock（getEvents），待後端 GET /events 就緒再切。
  useEffect(() => {
    getEvents(0, INITIAL_LOAD_SIZE).then((initial) => {
      setEvents(initial);
      setOffset(initial.length);
    });
  }, []);

  // 事件進場（event_created／event_updated 共用）：以 event_id upsert——
  // 已存在則就地更新該筆（吃 event_updated 與後端重送的同一 id），不存在則置頂新增。
  // pending 事件觸發全螢幕警示，警示以 id 去重避免重送造成重複彈窗。
  const handleIncomingEvent = useCallback((event: CareEvent) => {
    setEvents((prev) => {
      const exists = prev.some((e) => e.id === event.id);
      return exists ? prev.map((e) => (e.id === event.id ? event : e)) : [event, ...prev];
    });
    if (event.status === 'pending') {
      setConfirmedAlerts((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
    }
  }, []);

  // 真後端事件推播（SSE）。閒置不推，有事件才觸發 handleIncomingEvent。
  useEventSocket(session?.token ?? null, handleIncomingEvent);

  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), TICK_INTERVAL_MS);
    return () => clearInterval(tick);
  }, []);

  function dismissConfirmedAlert(id: string) {
    setConfirmedAlerts((prev) => prev.filter((event) => event.id !== id));
  }

  async function handleLoadMore() {
    const more = await getEvents(offset, PAGE_SIZE);
    setEvents((prev) => [...prev, ...more]);
    setOffset((prev) => prev + more.length);
  }

  // 「接手」：護理人員點選前往處理，事件轉「處理中」並記錄 assignee。清單卡與全螢幕警示都走這裡。
  // ⚠ 後端 /ack 是「送達確認」（收到即自動打，見 useEventSocket），非接手；後端尚無「接手」端點，
  //   故此處僅前端狀態更新，待後端補接手端點後再串接。
  async function acknowledgeEvent(event: CareEvent) {
    preAckSnapshotRef.current.set(event.id, event);
    const assignee = session?.display_name ?? null;
    const acknowledged: CareEvent = { ...event, status: 'in_progress', ack_deadline: null, assignee };
    setEvents((prev) => {
      const exists = prev.some((e) => e.id === event.id);
      return exists ? prev.map((e) => (e.id === event.id ? acknowledged : e)) : [acknowledged, ...prev];
    });
    dismissConfirmedAlert(event.id);
    setLastAckedId(event.id);
    setLastAckedEvent(acknowledged);
    setAckToastEvent(acknowledged);
    if (ackToastTimerRef.current) clearTimeout(ackToastTimerRef.current);
    ackToastTimerRef.current = setTimeout(() => {
      setAckToastEvent(null);
      setLastAckedEvent(null);
      preAckSnapshotRef.current.delete(event.id);
    }, ACK_TOAST_DURATION_MS);
  }

  // 後端尚無取消接手端點，復原僅回滾前端狀態並提示待後端補上。
  function undoAcknowledge(event: CareEvent) {
    console.warn('後端無取消接手端點，僅前端狀態回滾', event.id);
    const original = preAckSnapshotRef.current.get(event.id);
    if (!original) return;
    preAckSnapshotRef.current.delete(event.id);
    setEvents((prev) => prev.map((e) => (e.id === event.id ? original : e)));
    setConfirmedAlerts((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, original]));
    if (ackToastTimerRef.current) clearTimeout(ackToastTimerRef.current);
    setAckToastEvent(null);
    setLastAckedEvent(null);
  }

  // 標記誤報：verdict=false_alarm 並結案（後端 verdict + resolve）。
  async function resolveViaFeedback(event: CareEvent, label: FalseReportLabel, note: string) {
    try {
      await submitEventFeedback(event.id, { label, note });
    } catch (err) {
      console.warn('feedback API 呼叫失敗，僅前端狀態更新', err);
    }
    const resolved: CareEvent = { ...event, status: 'resolved', verdict: 'false_alarm' };
    setEvents((prev) => {
      const exists = prev.some((e) => e.id === event.id);
      return exists ? prev.map((e) => (e.id === event.id ? resolved : e)) : [resolved, ...prev];
    });
    dismissConfirmedAlert(event.id);
  }

  function clearLastAckedId() {
    setLastAckedId(null);
  }

  // 更新通報狀態：就地更新 context 內該筆事件，讓詳情頁與清單同步。後端補齊端點後於此改為呼叫 API。
  function updateReportStage(eventId: string, stage: ReportStage) {
    setEvents((prev) => prev.map((e) => (e.id === eventId ? { ...e, report_stage: stage } : e)));
  }

  // DEV-TEST：一鍵清空所有事件與警示相關狀態，把前端還原成無資料。移除測試功能時刪除此函式與 context 曝光。
  function clearTestEvents() {
    if (ackToastTimerRef.current) clearTimeout(ackToastTimerRef.current);
    preAckSnapshotRef.current.clear();
    setEvents([]);
    setOffset(0);
    setConfirmedAlerts([]);
    setLastAckedId(null);
    setAckToastEvent(null);
    setLastAckedEvent(null);
  }

  const value: EventsContextValue = {
    events,
    now,
    // SSE 事件直接併入清單，不再走「新事件橫幅」暫存，故 incomingEvent 恆為 null（保留介面相容）。
    incomingEvent: null,
    mergeIncomingEvent: () => {},
    handleLoadMore,
    handleAcknowledgeEvent: acknowledgeEvent,
    lastAckedId,
    clearLastAckedId,
    handleResolveViaFeedback: resolveViaFeedback,
    lastAckedEvent,
    undoAcknowledge,
    updateReportStage,
    // DEV-TEST：測試按鈕注入事件，直接複用真後端事件進場邏輯。移除測試功能時刪掉這兩行即可。
    injectTestEvent: handleIncomingEvent,
    clearTestEvents,
  };

  return (
    <EventsContext.Provider value={value}>
      {children}

      {confirmedAlerts.length > 0 && (
        <FullScreenAlert
          alerts={confirmedAlerts}
          now={now}
          onAcknowledge={acknowledgeEvent}
          onSuppress={resolveViaFeedback}
        />
      )}

      {ackToastEvent && (
        <div className="fixed right-6 bottom-6 z-[10000] flex items-center gap-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm text-[var(--text-primary)]">
          <span>
            已接手・復原：{ackToastEvent.camera.zone}（{ackToastEvent.camera.name}）
          </span>
          <button
            type="button"
            onClick={() => undoAcknowledge(ackToastEvent)}
            className="font-medium text-[var(--brand)] underline transition-colors duration-150"
          >
            復原
          </button>
        </div>
      )}
    </EventsContext.Provider>
  );
}

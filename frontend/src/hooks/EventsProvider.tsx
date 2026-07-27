import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { claimEvent, clearHazardEvent, getEvents, submitEventFeedback } from '../api/events';
import { FullScreenAlert } from '../components/FullScreenAlert';
import type { AlertLogEntry, CareEvent, FalseReportLabel } from '../types';

// 潛在危險（物件偵測）通知：組一筆「未回應事件」log（首頁右側用）。
function buildHazardLogEntry(event: CareEvent): AlertLogEntry {
  return {
    id: `${event.id}-hazard_detected-${Date.now()}`,
    eventId: event.id,
    cameraName: `${event.camera.zone}（${event.camera.name}）`,
    action: 'hazard_detected',
    hazardObject: event.hazard_object,
    at: new Date().toISOString(),
  };
}
import { EventsContext, type EventsContextValue } from './eventsContext';
import { useAuth } from './useAuth';
import { useEventSocket } from './useEventSocket';

const PAGE_SIZE = 3;
// 首頁「未結案事件」需一次顯示所有未結案事件、不分頁，故初始載入直接抓完全部事件；
// 「載入更多」（事件中心即時頁使用）仍維持每次 PAGE_SIZE 筆的漸進載入。
const INITIAL_LOAD_SIZE = 200;
const TICK_INTERVAL_MS = 1000;
const ACK_TOAST_DURATION_MS = 10000;
// 接手後須結案的處理時限：24 小時。倒數顯示於未結案列表與事件詳情頁。
const RESOLVE_WINDOW_MS = 24 * 60 * 60 * 1000;

export function EventsProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [events, setEvents] = useState<CareEvent[]>([]);
  const [offset, setOffset] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [confirmedAlerts, setConfirmedAlerts] = useState<CareEvent[]>([]);
  const [lastAckedId, setLastAckedId] = useState<string | null>(null);
  const [ackToastEvent, setAckToastEvent] = useState<CareEvent | null>(null);
  const [lastAckedEvent, setLastAckedEvent] = useState<CareEvent | null>(null);
  // 首頁右側「未回應事件」：目前只有潛在危險偵測會累積在這裡，最新在前（待處理事件由 Home.tsx 現算合併）。
  const [alertLog, setAlertLog] = useState<AlertLogEntry[]>([]);
  // 潛在危險（物件偵測）：不寫通報單、不與跌倒混流，獨立累積供首頁計數，最新在前。
  const [hazardEvents, setHazardEvents] = useState<CareEvent[]>([]);

  const ackToastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const preAckSnapshotRef = useRef<Map<string, CareEvent>>(new Map());

  // 初始清單走真後端 GET /events（新→舊），之後的新事件由 SSE 帶入。
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
    // 潛在危險（物件偵測）另走一條：不進 events、不跳全螢幕警示（無需通報單），僅累積供首頁計數，
    // 並記一筆 log 讓值班人員在首頁右側能立即看到偵測通知。
    if (event.event_type === 'hazard') {
      setHazardEvents((prev) => (prev.some((e) => e.id === event.id) ? prev : [event, ...prev]));
      setAlertLog((prev) =>
        prev.some((l) => l.eventId === event.id && l.action === 'hazard_detected')
          ? prev
          : [buildHazardLogEntry(event), ...prev],
      );
      return;
    }
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

  // 點擊首頁 log 的「待處理」行：重新跳出全螢幕警示彈窗；只是把彈窗叫回來，事件 status 不受影響。
  function reopenAlert(event: CareEvent) {
    setConfirmedAlerts((prev) => (prev.some((e) => e.id === event.id) ? prev : [...prev, event]));
  }

  async function handleLoadMore() {
    const more = await getEvents(offset, PAGE_SIZE);
    setEvents((prev) => [...prev, ...more]);
    setOffset((prev) => prev + more.length);
  }

  // 「接手」：護理人員點選前往處理，事件轉「處理中」並記錄 assignee。清單卡與全螢幕警示都走這裡。
  // ⚠ 後端 /ack 是「送達確認」（收到即自動打，見 useEventSocket），與接手是兩件事。
  // 接手走 claimEvent（實際打判定端點 true_alarm，見 api/events.ts 說明），後端才會真的轉 in_progress。
  // 先 await 後端再改前端狀態（非樂觀更新）：後端沒存成功就不該讓畫面顯示已接手，
  // 否則重整後狀態會退回待處理，等於騙使用者。失敗時警示留在畫面上讓人重按。
  async function acknowledgeEvent(event: CareEvent) {
    try {
      await claimEvent(event.id);
    } catch (err) {
      console.error('[acknowledgeEvent] 接手失敗，狀態未變更', event.id, err);
      return;
    }
    preAckSnapshotRef.current.set(event.id, event);
    const assignee = session?.display_name ?? null;
    // resolve_deadline 不在此設定：已改由 parseRawEvent 從事發時間現算（api/events.ts）
    const acknowledged: CareEvent = {
      ...event,
      status: 'in_progress',
      ack_deadline: null,
      assignee,
    };
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
    const resolved: CareEvent = {
      ...event,
      status: 'resolved',
      verdict: 'false_alarm',
      false_alarm_label: label,
      false_alarm_note: note.trim() || null,
    };
    setEvents((prev) => {
      const exists = prev.some((e) => e.id === event.id);
      return exists ? prev.map((e) => (e.id === event.id ? resolved : e)) : [resolved, ...prev];
    });
    dismissConfirmedAlert(event.id);
  }

  // 恢復事件：誤報紀錄中的事件拉回事件中心（處理中），清掉誤報判定與類型並重啟 24 小時時限。
  function restoreEvent(eventId: string) {
    const resolveDeadline = new Date(Date.now() + RESOLVE_WINDOW_MS).toISOString();
    setEvents((prev) =>
      prev.map((e) =>
        e.id === eventId
          ? {
              ...e,
              status: 'in_progress',
              verdict: null,
              false_alarm_label: null,
              false_alarm_note: null,
              resolve_deadline: resolveDeadline,
            }
          : e,
      ),
    );
  }

  function clearLastAckedId() {
    setLastAckedId(null);
  }

  // 重新向後端取事件清單。存完通報單／結案後呼叫，讓通報階段與狀態改由後端資料決定，
  // 前端不再自行推測（後端已回 report_stage／last_report_at，見 api/events.ts）。
  async function refreshEvents() {
    const latest = await getEvents(0, INITIAL_LOAD_SIZE);
    setEvents(latest);
    setOffset(latest.length);
  }

  // 潛在危險「已排除」：就地把該筆 hazard 標為 resolved，使其離開事件中心「潛在危險」頁、進入歷史「已排除危險」頁。
  // API 掛點在 api/events.ts clearHazardEvent（目前為 stub），fire-and-forget 比照 feedback 模式。
  function clearHazard(id: string) {
    clearHazardEvent(id).catch((err) => console.warn('clearHazardEvent API 呼叫失敗，僅前端狀態更新', err));
    setHazardEvents((prev) => prev.map((e) => (e.id === id ? { ...e, status: 'resolved' } : e)));
  }

  const value: EventsContextValue = {
    events,
    now,
    alertLog,
    confirmedAlerts,
    reopenAlert,
    hazardEvents,
    clearHazard,
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
    refreshEvents,
    restoreEvent,
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
          onDismiss={(event) => dismissConfirmedAlert(event.id)}
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

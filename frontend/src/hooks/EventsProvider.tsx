import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { claimEvent, clearHazardEvent, getEvents, submitEventFeedback } from '../api/events';
import { addBusinessDays } from '../utils/time';
import { FullScreenAlert } from '../components/FullScreenAlert';
import type { AlertLogAction, AlertLogEntry, CareEvent, FalseReportLabel, ReportStage } from '../types';

// 警示處理紀錄項目：由被處理的事件與動作組出一筆 log（首頁右側 log 用）。
function buildAlertLogEntry(event: CareEvent, action: AlertLogAction): AlertLogEntry {
  return {
    id: `${event.id}-${action}-${Date.now()}`,
    eventId: event.id,
    cameraName: `${event.camera.zone}（${event.camera.name}）`,
    action,
    hazardObject: action === 'hazard_detected' ? event.hazard_object : null,
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
  // 首頁右側 log：警示被接手／標記誤報後累積的處理紀錄，最新在前。
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
          : [buildAlertLogEntry(event, 'hazard_detected'), ...prev],
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
    // 記一筆處理紀錄（接手）到首頁 log，最新在前。
    setAlertLog((prev) => [buildAlertLogEntry(event, 'acknowledged'), ...prev]);
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
    // 復原接手＝撤回警示，連同 log 也移除該筆最新的「接手」紀錄，保持一致。
    setAlertLog((prev) => {
      const idx = prev.findIndex((l) => l.eventId === event.id && l.action === 'acknowledged');
      return idx === -1 ? prev : prev.filter((_, i) => i !== idx);
    });
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
    // 記一筆處理紀錄（誤報）到首頁 log。
    setAlertLog((prev) => [buildAlertLogEntry(event, 'false_alarm'), ...prev]);
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

  // 更新通報狀態：就地更新 context 內該筆事件，讓詳情頁與清單同步。後端補齊端點後於此改為呼叫 API。
  // 「已結報」(final) 視為結案 → status 轉 resolved，事件離開事件中心（未結案）並進入歷史紀錄；
  // 其餘階段（初報/續報）維持處理中，仍留在事件中心。
  // 一旦進入通報階段（已初報起），24 小時處理時限的倒數即清除（resolve_deadline 設 null，
  // CountdownTimer 遇 null 顯示「—」）——已通報即視為已處理，不再逼倒數。
  // 續報期限：初報與每次續報都重算，自當下起算 5 個工作日（排除週末），以日期顯示；結報無此期限。
  function updateReportStage(eventId: string, stage: ReportStage) {
    const followUpDeadline =
      stage === 'initial' || stage === 'follow_up'
        ? addBusinessDays(new Date().toISOString(), 5)
        : null;
    setEvents((prev) =>
      prev.map((e) =>
        e.id === eventId
          ? {
              ...e,
              report_stage: stage,
              status: stage === 'final' ? 'resolved' : 'in_progress',
              resolve_deadline: null,
              follow_up_deadline: followUpDeadline,
            }
          : e,
      ),
    );
  }

  // 潛在危險「已排除」：就地把該筆 hazard 標為 resolved，使其離開事件中心「潛在危險」頁、進入歷史「已排除危險」頁。
  // API 掛點在 api/events.ts clearHazardEvent（目前為 stub），fire-and-forget 比照 feedback 模式。
  function clearHazard(id: string) {
    clearHazardEvent(id).catch((err) => console.warn('clearHazardEvent API 呼叫失敗，僅前端狀態更新', err));
    setHazardEvents((prev) => prev.map((e) => (e.id === id ? { ...e, status: 'resolved' } : e)));
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
    setAlertLog([]);
    setHazardEvents([]);
  }

  const value: EventsContextValue = {
    events,
    now,
    alertLog,
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
    updateReportStage,
    restoreEvent,
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

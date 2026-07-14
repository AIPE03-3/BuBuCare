import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { getEvents, submitEventFeedback } from '../api/events';
import { FullScreenAlert } from '../components/FullScreenAlert';
import type { CareEvent, FalseReportLabel } from '../types';
import { EventsContext, type EventsContextValue } from './eventsContext';
import { useAuth } from './useAuth';
import { useEventSocket } from './useEventSocket';

const PAGE_SIZE = 3;
const TICK_INTERVAL_MS = 1000;
const ACK_TOAST_DURATION_MS = 10000;

// 離線 demo 後路：後端無法推事件時，按 Shift+A 手動塞一筆待處理事件觸發全螢幕警示。
function createDemoAlert(): CareEvent {
  return {
    id: `evt-demo-${Date.now()}`,
    event_type: 'fall',
    camera: { id: 12, name: '鏡頭12', zone: '北側3F樓梯間', floor: null, stream_url: null, stream_source: null, status: 'online' },
    occurred_at: new Date().toISOString(),
    status: 'pending',
    confidence: 0.92,
    vlm_result: {
      confidence: 0.93,
      severity: '高',
      description: '住民於樓梯間跌倒，倒地後無明顯自主移動。',
      suggestion: '請立即派員前往確認狀況並協助起身。',
    },
    verdict: null,
    clip_path: null,
    snapshot_path: null,
    assignee: null,
    notified_to: null,
    ack_deadline: null,
    escalated_to: null,
    alerted_at: new Date().toISOString(),
  };
}

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
    getEvents(0, PAGE_SIZE).then((initial) => {
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

    // 離線 demo 後路：Shift+A 手動觸發一筆警示。
    function handleKeyDown(e: KeyboardEvent) {
      if (e.shiftKey && e.key.toLowerCase() === 'a') {
        handleIncomingEvent(createDemoAlert());
      }
    }
    window.addEventListener('keydown', handleKeyDown);

    return () => {
      clearInterval(tick);
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleIncomingEvent]);

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

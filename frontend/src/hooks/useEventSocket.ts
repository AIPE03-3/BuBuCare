import { useEffect, useRef, useState } from 'react';
import { fetchEventSource } from '@microsoft/fetch-event-source';
import { BASE_URL, NGROK_HEADERS } from '../api/client';
import { acknowledgeEvent, parseRawEvent, type RawEventPayload } from '../api/events';
import type { CareEvent } from '../types';

export type SocketStatus = 'connecting' | 'open' | 'closed';

// 後端具名 SSE 事件：新事件與事件更新皆走 parseRawEvent，收到即回送達確認。
const EVENT_TYPES = new Set(['event_created', 'event_updated']);

/**
 * 連 fulilian-backend 的事件推播（SSE：GET /stream?token=...）。
 *
 * 用 @microsoft/fetch-event-source 而非原生 EventSource：原生 EventSource 無法帶自訂 header，
 * 會被 ngrok 免費版的訪客攔截頁擋下（跨來源請求 EventSource 也不帶 cookie，點過 Visit Site 亦無效）。
 * fetch-event-source 底層走 fetch，可帶 `ngrok-skip-browser-warning: true` 繞過。此問題僅 ngrok 測試環境有，
 * 正式部署不會遇到。token 仍走 query（後端設計）。
 *
 * 送達確認（ack）：後端有「保證送達」機制——每 10 秒檢查未 ack 的事件會重推同一 event_id，
 * 最多 3 次。前端一收到事件就自動打 POST /events/{id}/ack（純送達確認，不改狀態、不理回應），
 * 後端收到後即停止重送。搭配 EventsProvider 內以 event_id 去重，避免 ack 慢一步造成畫面重複。
 * ⚠ 此 ack 僅「送達確認」，與護理人員「接手」是兩回事，接手不走這裡。
 */
export function useEventSocket(token: string | null, onEvent: (event: CareEvent) => void): SocketStatus {
  // 有 token 才會連線；無 token 恆為 closed。初值直接由 token 推導，避免在 effect 內同步 setState。
  const [status, setStatus] = useState<SocketStatus>(token ? 'connecting' : 'closed');
  // onEvent 以 ref 保存，避免其身分變動導致 SSE 連線反覆重建。
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!token) return;

    const controller = new AbortController();

    fetchEventSource(`${BASE_URL}/stream?token=${encodeURIComponent(token)}`, {
      signal: controller.signal,
      headers: { ...NGROK_HEADERS },
      openWhenHidden: true, // 分頁切到背景時保持連線，值班畫面不應斷線
      onopen: async () => {
        setStatus('open');
      },
      onmessage: (msg) => {
        if (!EVENT_TYPES.has(msg.event)) return; // 略過心跳等未具名／其他事件
        try {
          const raw = JSON.parse(msg.data) as RawEventPayload;
          const event = parseRawEvent(raw);
          onEventRef.current(event);
          // 送達確認：告知後端已收到、停止重送。純背景，不理回應，失敗僅記 log（後端會重推）。
          acknowledgeEvent(event.id).catch((err) =>
            console.warn('[useEventSocket] 送達確認 ack 失敗（後端將重送）', event.id, err),
          );
        } catch (err) {
          console.warn('[useEventSocket] 事件解析失敗', err);
        }
      },
      onerror: (err) => {
        // 回傳（不 throw）讓 fetch-event-source 自動重連；狀態轉 connecting 供 UI 顯示重試中。
        setStatus('connecting');
        console.warn('[useEventSocket] SSE 連線錯誤，重試中', err);
      },
    }).catch(() => {
      // controller.abort() 造成的收尾例外，屬正常關閉，不需處理。
    });

    return () => controller.abort();
  }, [token]);

  return status;
}

import { createContext, useContext } from 'react';
import type { AlertLogEntry, CareEvent, FalseReportLabel } from '../types';

export interface EventsContextValue {
  events: CareEvent[];
  now: number;
  // 首頁右側「未回應事件」：目前只有潛在危險偵測會記在這裡；待處理（pending）事件由 pages/Home.tsx
  // 從 events 現算合併進來，不存在這裡。最新在前。
  alertLog: AlertLogEntry[];
  // 目前還開著全螢幕警示彈窗的事件：首頁 log 用來排除「還在彈窗中」的 pending 事件，避免跟彈窗重複顯示。
  confirmedAlerts: CareEvent[];
  // 點擊首頁 log 的「待處理」行：把該事件重新塞回 confirmedAlerts，讓全螢幕警示彈窗再跳出來一次。
  reopenAlert: (event: CareEvent) => void;
  // 潛在危險（物件偵測）事件：獨立於跌倒事件，不寫通報單。事件中心「潛在危險」頁與首頁計數共用。
  hazardEvents: CareEvent[];
  // 潛在危險「已排除」：標記為 resolved，移入歷史「已排除危險」頁。
  clearHazard: (id: string) => void;
  incomingEvent: CareEvent | null;
  mergeIncomingEvent: () => void;
  handleLoadMore: () => Promise<void>;
  handleAcknowledgeEvent: (event: CareEvent) => Promise<void>;
  lastAckedId: string | null;
  clearLastAckedId: () => void;
  handleResolveViaFeedback: (event: CareEvent, label: FalseReportLabel, note: string) => Promise<void>;
  lastAckedEvent: CareEvent | null;
  undoAcknowledge: (event: CareEvent) => void;
  // 重新向後端取事件清單（存完通報單／結案後呼叫，通報階段與狀態以後端為準）。
  refreshEvents: () => Promise<void>;
  // 恢復事件：誤報紀錄中的事件拉回事件中心（處理中），清誤報判定與類型並重啟時限。
  restoreEvent: (eventId: string) => void;
  // DEV-TEST：測試按鈕用，模擬後端推來一筆事件（走與真後端相同的 handleIncomingEvent）。移除測試功能時連同實作一併刪除。
  injectTestEvent: (event: CareEvent) => void;
  // DEV-TEST：一鍵清空所有事件與警示狀態，把前端還原成無資料。移除測試功能時連同實作一併刪除。
  clearTestEvents: () => void;
}

export const EventsContext = createContext<EventsContextValue | null>(null);

export function useEvents(): EventsContextValue {
  const ctx = useContext(EventsContext);
  if (!ctx) {
    throw new Error('useEvents 必須在 EventsProvider 內使用');
  }
  return ctx;
}

import { createContext, useContext } from 'react';
import type { CareEvent, FalseReportLabel, ReportStage } from '../types';

export interface EventsContextValue {
  events: CareEvent[];
  now: number;
  incomingEvent: CareEvent | null;
  mergeIncomingEvent: () => void;
  handleLoadMore: () => Promise<void>;
  handleAcknowledgeEvent: (event: CareEvent) => Promise<void>;
  lastAckedId: string | null;
  clearLastAckedId: () => void;
  handleResolveViaFeedback: (event: CareEvent, label: FalseReportLabel, note: string) => Promise<void>;
  lastAckedEvent: CareEvent | null;
  undoAcknowledge: (event: CareEvent) => void;
  // 更新通報狀態（初報/複報/結報）；demo 前端記憶體維護，後端補齊端點後改為呼叫 API。
  updateReportStage: (eventId: string, stage: ReportStage) => void;
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

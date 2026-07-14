import { createContext, useContext } from 'react';
import type { CareEvent, FalseReportLabel } from '../types';

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
}

export const EventsContext = createContext<EventsContextValue | null>(null);

export function useEvents(): EventsContextValue {
  const ctx = useContext(EventsContext);
  if (!ctx) {
    throw new Error('useEvents 必須在 EventsProvider 內使用');
  }
  return ctx;
}

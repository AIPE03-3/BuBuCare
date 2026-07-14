import type { CareEvent } from '../types';

export interface HomeEventGroups {
  needsAction: CareEvent[];
  inProgress: CareEvent[];
  resolvedToday: CareEvent[];
  suppressedTodayCount: number;
}

export function groupEventsForHome(events: CareEvent[]): HomeEventGroups {
  return {
    // 待處理（pending）且尚無人接手；曾升級者以 hasEscalatedFlag 另外標示，不再是獨立狀態。
    needsAction: events.filter((e) => e.status === 'pending' && e.assignee === null),
    inProgress: events.filter((e) => e.status === 'in_progress'),
    // 已結案（真跌倒）＝resolved 且非誤報；誤報另計。
    resolvedToday: events.filter((e) => e.status === 'resolved' && e.verdict !== 'false_alarm'),
    suppressedTodayCount: events.filter((e) => e.status === 'resolved' && e.verdict === 'false_alarm').length,
  };
}

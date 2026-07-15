import type { CareEvent } from '../types';

export function hasEscalatedFlag(event: CareEvent): boolean {
  return event.alerted_at !== null || event.escalated_to !== null;
}

// 事件類型顯示文字：誤報則顯示標記時選的類型（坐地/伸展…），否則「跌倒」。詳情頁與列表共用。
export function getEventTypeLabel(event: CareEvent): string {
  return event.verdict === 'false_alarm' && event.false_alarm_label
    ? event.false_alarm_label
    : '跌倒';
}

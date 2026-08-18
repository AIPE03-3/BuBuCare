import type { CareEvent, NotificationRecord } from '../types';

// 假資料已移除：通報紀錄回傳空清單，待後端 notifications 端點就緒後改為實際呼叫。
export async function getNotificationRecords(): Promise<NotificationRecord[]> {
  return [];
}

export interface NotificationWithEvent extends NotificationRecord {
  event: CareEvent | null;
}

export async function getNotificationRecordsWithEvents(): Promise<NotificationWithEvent[]> {
  return [];
}

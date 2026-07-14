import type { CareEvent, NotificationChannel, NotificationRecord, NotificationStatus } from '../types';
import { getEventById } from './events';
import rawNotifications from './mock/notifications.json';

/**
 * mock JSON 存的是相對於載入當下的 days_ago 偏移量，
 * 讓通報發送時間不會隨時間過去而失真，做法比照 api/envScores.ts。
 * 待後端提供正式 notifications 表資料（含 sent_at）後，此轉換與偏移量欄位一併整段刪除即可。
 */
interface RawNotification {
  id: string;
  event_id: string;
  channel: NotificationChannel;
  status: NotificationStatus;
  days_ago: number;
}

const PAGE_LOAD_TIME = Date.now();
const DAY_MS = 24 * 60 * 60 * 1000;

function daysAgoToIso(daysAgo: number): string {
  return new Date(PAGE_LOAD_TIME - daysAgo * DAY_MS).toISOString();
}

function toNotificationRecord(raw: RawNotification): NotificationRecord {
  return {
    id: raw.id,
    event_id: raw.event_id,
    channel: raw.channel,
    status: raw.status,
    sent_at: daysAgoToIso(raw.days_ago),
  };
}

const RAW_NOTIFICATIONS = rawNotifications as RawNotification[];
const NOTIFICATIONS: NotificationRecord[] = RAW_NOTIFICATIONS.map(toNotificationRecord);

export async function getNotificationRecords(): Promise<NotificationRecord[]> {
  return NOTIFICATIONS;
}

export interface NotificationWithEvent extends NotificationRecord {
  event: CareEvent | null;
}

export async function getNotificationRecordsWithEvents(): Promise<NotificationWithEvent[]> {
  return Promise.all(
    NOTIFICATIONS.map(async (record) => ({
      ...record,
      event: await getEventById(record.event_id),
    })),
  );
}

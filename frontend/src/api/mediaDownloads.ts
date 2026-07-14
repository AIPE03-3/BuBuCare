import type { DownloadableMedia } from '../types';
import rawMedia from './mock/downloadableMedia.json';

/**
 * mock JSON 存的是 expires_at_offset_days（相對載入當下的天數），
 * 讓「即將到期」「已過期」demo 資料不會隨時間過去而失真。
 * 待後端提供正式 expires_at／is_expired 判斷後，此轉換與 offset 欄位一併整段刪除即可。
 */
interface RawDownloadableMedia extends Omit<DownloadableMedia, 'expires_at' | 'is_expired'> {
  expires_at_offset_days: number;
}

const PAGE_LOAD_TIME = Date.now();
const DAY_MS = 24 * 60 * 60 * 1000;

function toDownloadableMedia(raw: RawDownloadableMedia): DownloadableMedia {
  const expiresAtMs = PAGE_LOAD_TIME + raw.expires_at_offset_days * DAY_MS;
  return {
    id: raw.id,
    media_type: raw.media_type,
    camera: raw.camera,
    status: raw.status,
    verdict: raw.verdict,
    false_alarm_type: raw.false_alarm_type,
    escalated: raw.escalated,
    captured_at: raw.captured_at,
    expires_at: new Date(expiresAtMs).toISOString(),
    is_expired: expiresAtMs <= PAGE_LOAD_TIME,
    download_url: raw.download_url,
  };
}

const MEDIA: DownloadableMedia[] = (rawMedia as RawDownloadableMedia[]).map(toDownloadableMedia);

// 後端目前無影像片段下載頁專用清單 API（見 04_後端現況與規格落差.md H 段），暫時走 mock，
// 介面維持 async 回傳 DownloadableMedia[]，之後只需替換函式內部實作即可接上真實 API。
export async function getDownloadableMedia(): Promise<DownloadableMedia[]> {
  return MEDIA;
}

import type { ReportFormData, SavedReport } from '../types';

// 通報單暫存於 localStorage（demo）：每個事件的通報單累積成一份「清單」（key＝eventId），
// 每次儲存（初報／續報／結報）都獨立新增一筆、不覆蓋，保留完整通報歷程。
// 未來接後端時只需改寫本檔各函式的實作（POST/GET /events/{id}/reports），呼叫端不需更動。
const REPORTS_KEY = 'fulilian_reports';

type ReportMap = Record<string, SavedReport[]>;

// 相容舊格式：早期為「每事件單筆」(SavedReport)，現為「每事件清單」(SavedReport[])。
// 讀取時把非陣列的舊值包成單元素陣列，避免既有 localStorage 資料讓 .filter/.length 出錯。
function readAll(): ReportMap {
  const raw = localStorage.getItem(REPORTS_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw) as Record<string, SavedReport | SavedReport[]>;
    const map: ReportMap = {};
    for (const [eventId, value] of Object.entries(parsed)) {
      map[eventId] = Array.isArray(value) ? value : [value];
    }
    return map;
  } catch {
    return {};
  }
}

function writeAll(map: ReportMap): void {
  localStorage.setItem(REPORTS_KEY, JSON.stringify(map));
}

// 介面一律 async：與 api/ 其他模組（cameras/users/events）一致，
// 呼叫端已按非同步寫（useEffect 載入），日後把實作換成 fetch 時呼叫端真的不用動。

// 儲存一筆通報單（獨立新增，不覆蓋既有紀錄），回傳存下的紀錄（含 savedAt）。
export async function saveReport(eventId: string, form: ReportFormData): Promise<SavedReport> {
  const record: SavedReport = { eventId, form, savedAt: new Date().toISOString() };
  const map = readAll();
  map[eventId] = [...(map[eventId] ?? []), record];
  writeAll(map);
  return record;
}

// 取某事件全部通報單，依儲存先後排序（陣列本身即時間序）。無則空陣列。
export async function getStoredReports(eventId: string): Promise<SavedReport[]> {
  return readAll()[eventId] ?? [];
}

// 取某事件最新一筆通報單（表單自動帶入、PDF 預覽、詳情頁判斷用）；無則 null。
export async function getLatestReport(eventId: string): Promise<SavedReport | null> {
  const list = await getStoredReports(eventId);
  return list.length > 0 ? list[list.length - 1] : null;
}

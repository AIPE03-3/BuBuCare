import { apiClient } from './client';
import { normalizeBackendTime } from '../utils/time';
import { REPORT_TYPE_TO_STAGE, type ReportFormData, type ReportStage, type SavedReport } from '../types';

/**
 * 通報單走真後端（POST/GET /events/{id}/reports）。
 * 每個事件的通報單累積成一份清單，每次儲存（初報／續報／結報）都獨立新增一筆、不覆蓋，
 * 保留完整通報歷程——這是後端的儲存規則，前端只負責送出與呈現。
 *
 * 表單內容（form）後端不驗、原樣保管，定義權完全在前端 ReportFormData，
 * 故欄位增減不需動後端；只有 report_type 三值是雙方共用契約。
 */

// 後端 GET/POST /events/{id}/reports 的回傳格式（backend/reports/router.py serialize_report）。
interface RawReportPayload {
  report_id: number;
  event_id: string;
  report_type: ReportStage;   // 與前端 ReportStage 同三值：initial/follow_up/final
  form: ReportFormData;       // 前端存什麼就回什麼，後端不加工
  created_by: string;         // 存這筆的人的員編（後端從 JWT 記，前端不帶）
  created_at: string;         // ISO，無時區標記
}

// 後端原始通報單 → 前端 SavedReport。
// ⚠ report_id 與 created_by（通報人員編）目前前端無顯示處，故不帶入 SavedReport；
//   日後通報歷程要顯示「誰通報的」時，於 types 補欄位再從這裡帶。
function parseRawReport(raw: RawReportPayload): SavedReport {
  return {
    eventId: raw.event_id,
    form: raw.form,
    savedAt: normalizeBackendTime(raw.created_at),
  };
}

// 儲存一筆通報單（後端獨立新增，不覆蓋既有紀錄），回傳存下的紀錄（含 savedAt）。
// report_type 由表單的中文通報別（初報／續報／結報）經 REPORT_TYPE_TO_STAGE 轉成後端三值，
// 對照表是全案唯一一份，禁止在此另寫轉換。呼叫端已保證 reportType 非空（原生 required）。
export async function saveReport(eventId: string, form: ReportFormData): Promise<SavedReport> {
  const raw = await apiClient.post<RawReportPayload>(`/events/${eventId}/reports`, {
    report_type: form.reportType ? REPORT_TYPE_TO_STAGE[form.reportType] : 'initial',
    form,
  });
  return parseRawReport(raw);
}

// 取某事件全部通報單。後端排序契約為舊→新（初報→續報→結報的歷程順序），前端不再重排。
export async function getStoredReports(eventId: string): Promise<SavedReport[]> {
  const raw = await apiClient.get<RawReportPayload[]>(`/events/${eventId}/reports`);
  return raw.map(parseRawReport);
}

// 取某事件最新一筆通報單（表單自動帶入、PDF 預覽、詳情頁判斷用）；無則 null。
// 取「最後一筆」成立的前提是上面的舊→新排序契約。
export async function getLatestReport(eventId: string): Promise<SavedReport | null> {
  const list = await getStoredReports(eventId);
  return list.length > 0 ? list[list.length - 1] : null;
}

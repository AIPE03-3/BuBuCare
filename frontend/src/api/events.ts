import { apiClient } from './client';
import { addBusinessDays, normalizeBackendTime } from '../utils/time';
import type {
  CareEvent,
  Camera,
  EventStatus,
  EventVerdict,
  FalseReportLabel,
  ReportStage,
  VlmResult,
} from '../types';
import { HAZARD_OBJECTS } from '../types';

/**
 * 後端 fulilian-backend 事件的原始 payload 欄位命名（SSE 推播與 GET /events 共用同一格式）。
 * 命名一律照後端實際欄位，非前端 CareEvent 命名。
 * 三個來源（SSE、GET /events、DevTestPanel 測試事件）都須先過 parseRawEvent 才能轉成 CareEvent，
 * 全案只保留這一套轉換邏輯。
 */
export interface RawEventPayload {
  event_id: string;
  device_id: number;
  device_name: string;
  // 位置名稱（後端 locations.location_name），事件發生當下凍結；事件沒凍到位置時為 null。
  // ⚠ 後端不帶樓層（floor 只在 GET /devices 有），事件端一律無樓層資訊。
  location: string | null;
  event_type: string;
  status: string;               // 已對齊三態 pending/in_progress/resolved，值不需轉換
  verdict: string | null;       // 已對齊 true_alarm/false_alarm/null，值不需轉換
  clip_path: string | null;
  snapshot_path: string | null;
  detected_at: string;          // ISO
  notified_at: string | null;
  verdict_by: string | null;    // 判定者員編（後端從 JWT 記，前端不帶）
  verdict_by_name: string | null;   // 判定者姓名（後端 JOIN user_account 夾帶，供顯示；查不到為 null）
  resolved_by: string | null;   // 結案者員編（同上）
  resolved_by_name: string | null;  // 結案者姓名（同上）
  company_id: number;
  yolo_score: number;
  vlm_summary: string | null;   // VLM 情境描述純文字（後端 DB 為 Text 欄位）
  report_stage: string | null;  // 最新一筆通報單的類型（initial/follow_up/final），無通報單為 null
  last_report_at: string | null; // 最新一筆通報單的儲存時間，續報期限由此起算
  hazard_object?: string | null; // 潛在危險事件才有；後端實際欄位未定，先預留（見 DevTestPanel）
}

/**
 * 後端原始事件 payload → 前端 CareEvent。
 * 欄位對應已對照後端 serialize_event（backend/events/service.py）確認，
 * SSE 廣播與 GET /events 兩條路徑用的是同一份 payload，故共用本函式。
 */
// 結案時限：自事發起算 24 小時。用 detected_at（後端欄位）而非接手時間——
// 後端沒存判定時間，且從事發起算才不會「沒人接手就不開始倒數」。
const RESOLVE_WINDOW_MS = 24 * 60 * 60 * 1000;

export function parseRawEvent(raw: RawEventPayload): CareEvent {
  const camera: Camera = {
    id: raw.device_id,
    name: raw.device_name,
    zone: raw.location ?? '',
    // 後端事件 payload 不帶樓層（僅 GET /devices 有），故固定 null。
    floor: null,
    // 後端事件 payload 無串流網址與在線狀態（僅 GET /devices 有），先固定值，非程式邏輯遺漏。
    stream_url: null,
    stream_source: null,
    status: 'online',
  };

  // vlm_summary 為純文字描述，null＝YOLO 高信心直通（整個 vlm_result 回 null）。
  // suggestion 後端無對應欄位，留空。
  // severity 已於 2026-07-19（後端 commit 1bbb585）從 detect_events 與事件 API 整組移除，
  // 嚴重度概念改用 verdict_by / resolved_by 取代；這裡原本寫死「中」，沒有任何元件讀它，一併刪除。
  const vlm_result: VlmResult | null =
    raw.vlm_summary === null
      ? null
      : {
          confidence: raw.yolo_score,
          description: raw.vlm_summary,
          suggestion: '',
        };

  return {
    id: raw.event_id,
    // hazard＝物件偵測（危險物品）；其餘一律當跌倒。後端 hazard 實際字串未定，先以 'hazard' 對應（見 DevTestPanel）。
    event_type: raw.event_type === 'hazard' ? 'hazard' : 'fall',
    // 危險物品類型：僅取後端有效值，其餘一律 null（跌倒事件亦為 null）。
    hazard_object: HAZARD_OBJECTS.find((o) => o === raw.hazard_object) ?? null,
    camera,
    occurred_at: normalizeBackendTime(raw.detected_at),
    status: raw.status as EventStatus,   // 後端已對齊三態，僅換欄位名，值不轉換
    // 通報階段由後端從通報單表算出（值與前端 ReportStage 相同），前端不再自行維護
    report_stage: raw.report_stage as ReportStage | null,
    confidence: raw.yolo_score,
    vlm_result,
    verdict: raw.verdict as EventVerdict, // 後端已對齊 true_alarm/false_alarm/null
    // 誤報類型與備註後端尚無對應欄位，一律 null；由前端標記誤報（resolveViaFeedback）時寫入。
    false_alarm_label: null,
    false_alarm_note: null,
    clip_path: raw.clip_path,
    snapshot_path: raw.snapshot_path,
    // assignee 取後端判定者：本案「接手」就是打判定端點（見 claimEvent），判定者即接手者。
    // 優先顯示姓名（verdict_by_name），後端查不到姓名時退回員編（verdict_by），不會空白。
    assignee: raw.verdict_by_name ?? raw.verdict_by,
    // 以下欄位後端 MVP 階段尚無對應來源，固定 null（非漏接，後端補齊後再帶入）：
    notified_to: null,
    ack_deadline: null,
    // 每次從後端資料現算，故重整後倒數仍在（先前是接手當下才寫入、只活在記憶體）
    // 已進入通報階段就不再倒數（已通報即視為已處理）
    resolve_deadline: raw.report_stage
      ? null
      : new Date(
          new Date(normalizeBackendTime(raw.detected_at)).getTime() + RESOLVE_WINDOW_MS,
        ).toISOString(),
    // 續報期限＝最新一筆通報單起算 5 個工作日；結報無此期限
    follow_up_deadline:
      raw.last_report_at && (raw.report_stage === 'initial' || raw.report_stage === 'follow_up')
        ? addBusinessDays(normalizeBackendTime(raw.last_report_at), 5)
        : null,
    escalated_to: null,
    alerted_at: null,
  };
}

// 初始清單／載入更多：後端 GET /events 回全部事件（新→舊），與 SSE 同一份 payload 格式。
// ⚠ 後端無 offset/limit 參數，分頁由前端自行切片；事件量大到不堪負荷時再請後端加 query 參數。
export async function getEvents(offset: number, limit: number): Promise<CareEvent[]> {
  const raw = await apiClient.get<RawEventPayload[]>('/events');
  return raw.slice(offset, offset + limit).map(parseRawEvent);
}

// 送達確認：後端 POST /events/{id}/ack，無 request body，回 { status: 'ok' }。
// 用途是告知後端「這筆 SSE 事件已收到」，關掉後端每 10 秒最多 3 次的重送機制。
// ⚠ 非「接手」——接手是護理人員動作（見 EventsProvider），後端目前無對應端點。
export async function acknowledgeEvent(id: string): Promise<void> {
  await apiClient.post(`/events/${id}/ack`);
}

// 接手（「確認前往處理」）：後端沒有獨立的接手端點，改打判定端點 verdict=true_alarm——
// 後端收到 true_alarm 會把 status 從 pending 轉成 in_progress，正是接手要的效果，
// 且會自動把按鈕的人（JWT 員編）記進 verdict_by，「誰接手的」一併留痕。
// ⚠ 語意上判定與接手仍是兩件事（見 04 檔 C#19）；日後後端補獨立的 acknowledge 端點時改打那支即可。
export async function claimEvent(id: string): Promise<void> {
  await apiClient.patch(`/events/${id}/verdict`, { verdict: 'true_alarm' });
}

// 結案：後端 PATCH /events/{id}/resolve，只收處理中的事件，結案者由後端從 JWT 記入。
// 結報（final）時呼叫——存通報單本身不會結案，兩件事後端是分開的。
export async function resolveEvent(id: string): Promise<void> {
  await apiClient.patch(`/events/${id}/resolve`);
}

// 標記誤報＝先下 verdict=false_alarm，再 resolve 結案（後端兩支端點）。
// body.label／note 目前後端 verdict 端點未收（僅 verdict＋staff_id），先記進 log，
// 待後端補「誤報原因」欄位後改帶入 request body。
export async function submitEventFeedback(
  id: string,
  body: { label: FalseReportLabel; note: string },
): Promise<void> {
  console.info('[submitEventFeedback] 誤報原因（待後端補欄位後上傳）', id, body);
  await apiClient.patch(`/events/${id}/verdict`, { verdict: 'false_alarm' });
  await apiClient.patch(`/events/${id}/resolve`);
}

// 潛在危險「已排除」：後端 hazard 事件規格未定、尚無對應端點，先只記 log 佔位。
// 端點就緒後改為實際呼叫（候選：PATCH /events/{id}/resolve，與誤報共用 resolve）。
export async function clearHazardEvent(id: string): Promise<void> {
  console.info('[clearHazardEvent] 後端端點未定，僅前端狀態更新', id);
}

// 事發影片／截圖限時網址：後端把 clip_path/snapshot_path 的 s3:// 現轉成約 1 小時有效的網址。
// ⚠ 兩者皆可能為 null（舊事件無雲端影片）；網址會過期，不快取、不存進 redux，每次開啟畫面重新呼叫。
export interface EventMedia {
  clip_url: string | null;
  snapshot_url: string | null;
}

export async function getEventMedia(id: string): Promise<EventMedia> {
  return apiClient.get<EventMedia>(`/events/${id}/media`);
}

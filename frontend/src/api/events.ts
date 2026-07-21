import { apiClient } from './client';
import { normalizeBackendTime } from '../utils/time';
import type {
  CareEvent,
  Camera,
  EventStatus,
  EventVerdict,
  FalseReportLabel,
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
  resolved_by: string | null;   // 結案者員編（同上）
  company_id: number;
  yolo_score: number;
  vlm_summary: string | null;   // VLM 情境描述純文字（後端 DB 為 Text 欄位）
  hazard_object?: string | null; // 潛在危險事件才有；後端實際欄位未定，先預留（見 DevTestPanel）
}

/**
 * 後端原始事件 payload → 前端 CareEvent。
 * 欄位對應已對照後端 serialize_event（backend/events/service.py）確認，
 * SSE 廣播與 GET /events 兩條路徑用的是同一份 payload，故共用本函式。
 */
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
  // severity／suggestion 後端無對應欄位：severity 固定「中」（避免 UI 誤標高危），suggestion 留空。
  const vlm_result: VlmResult | null =
    raw.vlm_summary === null
      ? null
      : {
          confidence: raw.yolo_score,
          severity: '中',
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
    // 通報狀態後端尚無對應欄位，一律 null（尚未通報），由前端詳情頁按鈕更新。後端補齊後改由 raw 帶入。
    report_stage: null,
    confidence: raw.yolo_score,
    vlm_result,
    verdict: raw.verdict as EventVerdict, // 後端已對齊 true_alarm/false_alarm/null
    // 誤報類型與備註後端尚無對應欄位，一律 null；由前端標記誤報（resolveViaFeedback）時寫入。
    false_alarm_label: null,
    false_alarm_note: null,
    clip_path: raw.clip_path,
    snapshot_path: raw.snapshot_path,
    // assignee＝「接手處理的人」，直接取後端的 verdict_by（員編字串，如 "staff01"）。
    // 本案「接手」就是打判定端點 true_alarm（見下方 claimEvent），按鈕按下去的人會被後端從 JWT
    // 記進 verdict_by——判定者即接手者，是同一個人，故可直接對應。
    // 這樣接手人是從 DB 讀回來的，重整頁面不會消失（先前寫死 null，接手人只活在前端記憶體裡）。
    assignee: raw.verdict_by,
    // 以下欄位後端 MVP 階段尚無對應來源，固定 null（非漏接，後端補齊後再帶入）：
    notified_to: null,
    ack_deadline: null,
    // 尚未接手，故無 24 小時結案時限；接手（acknowledgeEvent）當下才寫入。
    resolve_deadline: null,
    // 續報期限於初報（updateReportStage stage='initial'）時才計算，此前為 null。
    follow_up_deadline: null,
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

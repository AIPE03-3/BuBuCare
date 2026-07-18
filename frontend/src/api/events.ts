import { apiClient } from './client';
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
 * 後端 fulilian-backend 事件推播（SSE）的原始 payload 欄位命名。
 * 命名一律照後端實際欄位，非前端 CareEvent 命名，也非現有 mock 命名。
 * mock 與未來真實 SSE 皆須先過 parseRawEvent 才能轉成 CareEvent，
 * 全案只保留這一套轉換邏輯。
 */
export interface RawEventPayload {
  event_id: string;
  device_id: number;
  device_name: string;
  // ⚠ location、vlm_summary 兩欄後端實際格式尚未確認（字串 or 物件皆可能），
  //   parseRawEvent 內以 runtime typeof 判斷兩種格式都吃，實際格式確認後可簡化。
  location: string | { zone?: string; floor?: string };
  event_type: string;
  status: string;               // 已對齊三態 pending/in_progress/resolved，值不需轉換
  verdict: string | null;       // 已對齊 true_alarm/false_alarm/null，值不需轉換
  clip_path: string | null;
  snapshot_path: string | null;
  detected_at: string;          // ISO
  notified_at: string | null;
  staff_id: number | null;
  company_id: number;
  yolo_score: number;
  yolo_threshold: number;
  vlm_summary: string | { confidence?: number; description?: string; suggestion?: string } | null;
  severity: string | null;
  hazard_object?: string | null; // 潛在危險事件才有；後端實際欄位未定，先預留（見 DevTestPanel）
}

/**
 * 後端原始事件 payload → 前端 CareEvent。
 * 格式已確認的欄位直接照 RawEventPayload 型別寫死轉換；
 * 格式未確認的 location、vlm_summary 以 typeof 防呆，兩種格式都能吃。
 */
export function parseRawEvent(raw: RawEventPayload): CareEvent {
  // location：格式未確認 —— 可能是純字串（當作 zone），也可能是 { zone, floor } 物件。
  // 實際格式確認後可簡化為單一分支。
  let zone: string;
  let floor: string | null;
  if (typeof raw.location === 'string') {
    zone = raw.location;
    floor = null;
  } else {
    zone = raw.location?.zone ?? '';
    floor = raw.location?.floor ?? null;
  }

  const camera: Camera = {
    id: raw.device_id,
    name: raw.device_name,
    zone,
    floor,
    // 後端目前無 /devices 端點可查串流網址與在線狀態，先固定值，非程式邏輯遺漏。
    stream_url: null,
    stream_source: null,
    status: 'online',
  };

  // vlm_summary：格式未確認 —— 可能是純字串（當作 description），也可能是完整物件。
  // 為 null 時整個 vlm_result 回傳 null（YOLO 高信心直通）。實際格式確認後可簡化。
  let vlm_result: VlmResult | null;
  if (raw.vlm_summary === null) {
    vlm_result = null;
  } else if (typeof raw.vlm_summary === 'string') {
    vlm_result = {
      confidence: raw.yolo_score,
      severity: normalizeSeverity(raw.severity),
      description: raw.vlm_summary,
      suggestion: '',
    };
  } else {
    vlm_result = {
      confidence: raw.vlm_summary.confidence ?? raw.yolo_score,
      severity: normalizeSeverity(raw.severity),
      description: raw.vlm_summary.description ?? '',
      suggestion: raw.vlm_summary.suggestion ?? '',
    };
  }

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
    // staff_id → assignee：後端尚無 GET /staff 名單可對姓名，先以「員工 #<id>」過渡呈現，
    // 讓孤立數字有語意；名單就緒後改帶真實姓名即可。
    assignee: raw.staff_id === null ? null : `員工 #${raw.staff_id}`,
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

// severity 後端實際格式尚未確認（可能中文「高/中/低」、英文 high/mid/low，甚至別的字串），
// 比照 location/vlm_summary 用 runtime 對照兩種語系都接住，實際格式確認後可簡化對照表。
// 無法辨識的值 fallback 到「中」，並 console.warn 讓第一次遇到不吻合的值會浮上檯面，
// 而非默默 fallback 掉、自己都不知道對錯。
function normalizeSeverity(severity: string | null): VlmResult['severity'] {
  switch (severity?.toLowerCase()) {
    case '高':
    case 'high':
      return '高';
    case '中':
    case 'mid':
    case 'medium':
      return '中';
    case '低':
    case 'low':
      return '低';
    default:
      console.warn('[parseRawEvent] 未知的 severity 值：', severity);
      return '中';
  }
}

// 後端 detected_at 記的是台灣本地時間（UTC+8）但漏帶時區標記（例：'2026-07-11T18:51:34.300114'）。
// JS 的 new Date() 對「不帶時區」的 ISO 字串會當 UTC 解讀，導致顯示時間平白差 8 小時（如「已經過 28818 秒」）。
// 這裡對「無時區標記」的字串補上 +08:00；已帶 Z 或 ±hh:mm 者原樣返回，
// 待後端改回帶時區 ISO 後此函式自動不再加工。全案時間顯示／排序都吃 occurred_at，故只需在此正規化一次。
function normalizeBackendTime(iso: string): string {
  const hasTimezone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
  return hasTimezone ? iso : `${iso}+08:00`;
}

// 初始清單：後端尚無 GET /events 端點，先回空陣列，事件一律由 SSE（handleIncomingEvent）帶入。
// 端點就緒後改為：apiClient.get<RawEventPayload[]>(`/events?offset=&limit=`) 再逐筆 parseRawEvent。
export async function getEvents(offset: number, limit: number): Promise<CareEvent[]> {
  void offset;
  void limit;
  return [];
}

// 送達確認：後端 POST /events/{id}/ack，無 request body，回 { status: 'ok' }。
// 用途是告知後端「這筆 SSE 事件已收到」，關掉後端每 10 秒最多 3 次的重送機制。
// ⚠ 非「接手」——接手是護理人員動作（見 EventsProvider），後端目前無對應端點。
export async function acknowledgeEvent(id: string): Promise<void> {
  await apiClient.post(`/events/${id}/ack`);
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

// MVP：對齊後端實際三態（凱莉 fulilian-backend）
export type EventStatus = 'pending' | 'in_progress' | 'resolved';

export const STATUS_LABEL: Record<EventStatus, string> = {
  pending: '待處理', in_progress: '處理中', resolved: '已結案',
};

// 即時監控頁：偵測到疑似跌倒事件的鏡頭縮圖標籤（非 EventStatus，獨立於 STATUS_LABEL 之外）
export const DETECTING_LABEL = '偵測中';

// 即時監控頁：離線鏡頭縮圖標籤
export const OFFLINE_LABEL = '離線';

// 鏡頭縮圖／事件快照灰色占位框文字，全案共用一份，禁止散落各自硬編碼
export const CAMERA_LABEL = {
  SNAPSHOT_PLACEHOLDER: '事件快照（影像片段）',
} as const;

// 誤報非獨立狀態，改由 verdict 判斷（後端：誤報＝verdict false_alarm 且直接 resolved）
export type EventVerdict = 'true_alarm' | 'false_alarm' | null;

// 事件中心即時處理頁的篩選值：'all' ＋ 三態。
export type EventFilter = 'all' | EventStatus;

// 即時處理頁只顯示「處理中／今日已結案」，待處理的新事件走全螢幕警示與新事件橫幅。
export const EVENT_CENTER_LIVE_FILTERS: EventFilter[] = ['all', 'in_progress', 'resolved'];

// 逾時升級 UI、已升級篩選，皆待後端補齊 escalation 欄位後再實作。

export type FalseReportLabel = '坐地' | '伸展' | '彎腰' | '攙扶' | '其他';

// 鏡頭串流來源：目前 mock 資料僅有 null（無串流來源）這一種情境。
// 'snapshot'／'hls' 為後續輪次接上真實影像來源時使用，本輪只定義型別、不實作渲染。
export type StreamSource =
  | { type: 'snapshot'; url: string }
  | { type: 'hls'; url: string }
  | null;

// 裝置狀態：online=正常運作／offline=暫時離線（監控死角，需注意）／disabled=永久已停用（排除總覽查詢）。
// ⚠ 待後端確認 devices.status 是否已區分 offline/disabled（04檔#5），MVP 前端先預留三態、mock 資料模擬。
export type DeviceStatus = 'online' | 'offline' | 'disabled';

export interface Camera {
  id: number;
  name: string;              // 鏡頭5
  zone: string;              // 活動室A（區域分組，無樓層層）
  floor: string | null;      // demo 一律不顯示
  stream_url: string | null; // 串流協定未定，先預留（既有欄位，勿動——FullScreenAlert/SuppressConfirmModal 仍依賴此欄位）
  stream_source: StreamSource; // 畫面渲染來源；本輪 mock 資料一律為 null，見 CameraCard 渲染分支
  status: DeviceStatus;      // 取代原本 online: boolean，支援離線/已停用分開判斷（online 布林可由 status==='online' 導出）
}

export interface VlmResult {
  confidence: number;
  severity: '高' | '中' | '低';
  description: string;
  suggestion: string;
}

export interface CareEvent {
  id: string;
  event_type: 'fall';
  camera: Camera;
  occurred_at: string;       // ISO
  status: EventStatus;
  confidence: number;        // YOLO 初篩
  vlm_result: VlmResult | null;  // ★ null＝YOLO 高分直通，UI 需顯示「YOLO 高信心直通」且不得噴錯
  verdict: EventVerdict;     // 判定結果，'false_alarm'＝誤報，UI「誤報」標籤依此判斷（非 status）
  clip_path: string | null;      // ← 事件影片片段路徑，詳情頁播放器用
  snapshot_path: string | null;  // ← 事件快照圖片路徑，卡片縮圖／彈窗用
  assignee: string | null;
  notified_to: string | null;
  ack_deadline: string | null;   // 接手時限（ISO），pending 時有值，用於逾時倒數
  escalated_to: string | null;   // 升級通知對象；待班表系統導入後帶入實際值班人員，demo 暫以當日值班組長代替
  alerted_at: string | null;     // 曾以全螢幕警示呈現的時間（ISO），用於「⚠ 曾全螢幕警示」持久徽章
  stage_latency_ms?: { capture: number; inference: number; emit: number }; // 預留，本期不顯示
}

export interface EventHistoryQuery {
  // 歷史終態一律 resolved，真跌倒／誤報改由 verdict 區分；undefined＝全部（不分 verdict）。
  verdict?: 'true_alarm' | 'false_alarm';
  escalatedOnly?: boolean;            // 獨立「只顯示曾升級」快速切換，AND 邏輯
  from?: string;                       // ISO，區間起
  to?: string;                         // ISO，區間迄
  page: number;
  pageSize: number;
}

export interface PagedResult<T> {
  items: T[];
  total: number;
}

export interface EventHistoryStatPoint {
  date: string; // YYYY-MM-DD
  true_alarm: number;  // 已結案（真跌倒）件數
  false_alarm: number; // 誤報件數
}

// 環境安全評分（IA 4-1/4-2）：四向度定案 2026-07-12（地面30/通道30/危險物品20/照明20，不含安全設施完整性）。
// 後端 env_safety_scores 表尚未建立，另一 branch 目前僅二分文字判斷、無分數（見 04_後端現況與規格落差.md A-6/A-7），
// 本輪全走 mock，型別照規格 schema 設計，之後接真分數只需換 api/envScores.ts 內部實作。
export type EnvScoreLevel = '良好' | '注意' | '警示' | '危險';

export interface EnvDimensionScore {
  score: number;
  max: number;
  level: EnvScoreLevel;
}

export interface EnvScore {
  score_id: string;
  camera: Camera;
  total_score: number | null;       // null＝後端僅二分文字時的過渡狀態
  dimensions: {
    floor: EnvDimensionScore;       // 地面地板，滿分 30
    pathway: EnvDimensionScore;     // 通道暢通性，滿分 30
    hazard: EnvDimensionScore;      // 潛在危險物品，滿分 20
    lighting: EnvDimensionScore;    // 照明條件，滿分 20
  } | null;
  level: EnvScoreLevel | null;
  overall_description: string | null;
  risk_factors: string[];           // 格式未定，暫定 string[]，待後端 JSONB 實際格式確認
  score_drop: number | null;        // 計算基準未定，待後端 score_drop 定義確認
  online: boolean;
  assessed_at: string;              // ISO 字串
}

// Hard Negative Pool（MLOps 6-2）
// ⚠ 語意提醒：MVP 沿用 02 規格「人工標記誤報」語意；後端實際現況為 YOLO 信心自動收集、存檔案系統，
//    與人工標記無關，此落差尚未拍板（見 04 檔 H 段），正式串接前需重新確認。
export type HnpLabel = '坐地' | '伸展' | '彎腰' | '攙扶' | '其他';

export interface HardNegativeItem {
  id: string;
  event_id: string;
  camera: Camera;
  label: HnpLabel;
  note: string | null;
  labeled_by: string;   // ⚠ 見上方語意提醒
  labeled_at: string;   // ISO
  clip_path: string | null; // 影片回放用
}

// 環境安全評分歷史（IA 7-2）：逐筆聚合時間序列，形狀不同於上面「每台最新一筆」的 EnvScore。
// EnvSafetyGrade 與 EnvScoreLevel 同義（四值一致），以別名維持全案單一定義、避免兩套同義型別。
export type EnvSafetyGrade = EnvScoreLevel;

export interface EnvSafetyScore {
  score_id: string;
  device_id: number;
  total_score: number;       // 0-100，四向度加總（地面30/通道30/危險物品20/照明20，2026-07-12定案）
  grade: EnvSafetyGrade;     // 前端依 total_score 對照門檻算出（getEnvScoreLevel），非後端原始欄位
  score_drop: number | null; // 較前次變化；null＝無前次可比較（如離線後首筆）
  assessed_at: string;       // ISO
}

// 時間區間下拉：對應聚合粒度（≤24h 原始15分級距／1–7天每小時最低分／>7天每日最低分，皆取最低分非平均）。
export type EnvHistoryRange = 'today' | '7d' | '30d' | 'custom';

export interface KpiSummary {
  pending_events: number;
  false_positive_rate: number;
  env_score_avg: number;
  env_score_threshold: number;   // 低於此值數字轉 --danger
  hnp_count: number;
  hnp_threshold: number;         // 達標數字轉 --warning
}

// 影像片段下載頁（IA 7-4）：事件影片（對應未來 detect_events.clip_path）與環境截圖（無事件狀態）的合併清單。
// 後端目前無對應 API（見 04_後端現況與規格落差.md H 段），本輪全走 mock，資料層留可換真 API 的介面。
export type DownloadableMediaType = 'event_clip' | 'env_snapshot';

export interface DownloadableMedia {
  id: string;
  media_type: DownloadableMediaType;
  camera: Camera;
  status: EventStatus | null;        // env_snapshot 固定 null（無事件狀態）
  verdict: EventVerdict;
  false_alarm_type: FalseReportLabel | null;
  escalated: boolean;                // 對應 alerted_at 或 escalated_to 任一非 null；旗子圖示疊加用，非獨立狀態值
  captured_at: string;                // ISO
  expires_at: string;                 // ISO
  is_expired: boolean;                // mock 先自行計算，待後端提供正式判斷
  download_url: string | null;
}

export type Role = 'admin' | 'staff';
export interface AuthSession { token: string; role: Role; display_name: string; }
export interface AuthProvider {
  requestCode?(email: string): Promise<void>;
  verifyCode?(email: string, code: string): Promise<AuthSession>;
  loginWithPassword?(employeeId: string, password: string): Promise<AuthSession>;
  logout(): void;
}

// 通報紀錄頁（IA 7-3，🔒 admin-only）：Web Push 逐筆送達紀錄。
// 後端 notifications 表已有 notify_id/event_id/channel/status/sent_at（見 02_需求規格速查.md），本輪全走 mock。
export type NotificationChannel = 'web_push'; // MVP 僅一種，UI 用下拉不寫死文字，預留未來擴充（8-6 通報管道）
export const CHANNEL_LABEL: Record<NotificationChannel, string> = { web_push: 'Web Push' };

export type NotificationStatus = 'delivered' | 'failed';
export const NOTIFICATION_STATUS_LABEL: Record<NotificationStatus, string> = {
  delivered: '已送達', failed: '發送失敗',
};

export interface NotificationRecord {
  id: string;
  event_id: string;   // 對應 CareEvent.id，唯讀彈窗資料從這裡撈
  channel: NotificationChannel;
  sent_at: string;    // ISO
  status: NotificationStatus;
}

// MLOps 每日效能指標（IA 6-1）：model_daily_metrics 表對應型別。
// 後端表與 /mlops/metrics 端點尚未建立（04_後端現況與規格落差.md A-7），本輪全走 mock，
// 資料層照規格 schema 設計，之後接真 API 只需換 src/api/mlops.ts 內部實作。
export interface ModelDailyMetric {
  id: string;
  device_id: number | null;      // null＝全域彙總（跨攝影機）
  date: string;                   // YYYY-MM-DD
  yolo_trigger_count: number;
  false_positive_count: number;
  avg_confidence: number;         // 0-1
  vlm_override_rate: number;      // 0-1，VLM 推翻 YOLO 初判的比例
  hard_negative_pool_size: number;
}

// 模型版本狀態（MLOps 6-3~6-6，MVP 三態；#8 若後端未來新增「訓練中」需再擴充）
export type ModelVersionStatus = 'staging' | 'production' | 'retired';

export const MODEL_VERSION_STATUS_LABEL: Record<ModelVersionStatus, string> = {
  staging: '待審核',
  production: '上線中',
  retired: '已下架',
};

// 樣式對照（借用既有 StatusTag 視覺邏輯，不新增色票）：
// staging    → 比照 in_progress：深色外框、透明底
// production → 比照 resolved：--success-bg 底 + --success 字
// retired    → 比照 誤報/離線：灰字、空心外框、無底色

export interface ModelVersion {
  version_id: string;
  version_tag: string;          // 例如 v1.3.0
  model_type: string;           // 例如 yolo_fall_detect
  status: ModelVersionStatus;
  recall: number;
  false_positive_rate: number;
  map_50: number;
  deployed_at: string | null;   // production 才有值
  created_at: string;
}

// 固定測試集（MLOps 6-7，唯讀）
export interface FixedTestSetComposition {
  category: '正樣本' | HnpLabel;  // 正樣本，或沿用既有 HnpLabel（坐地/伸展/彎腰/攙扶/其他）
  count: number;
}

export interface DeploymentThreshold {
  metric: string;          // 例如 'Recall（召回率）'
  threshold_text: string;  // 純文字規則，例如 '≥ 現行 Production 版本'
}

export interface FixedTestSet {
  is_frozen: boolean;
  created_at: string;  // ISO
  composition: FixedTestSetComposition[];
  thresholds: DeploymentThreshold[];
}

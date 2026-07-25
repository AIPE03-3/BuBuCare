// MVP：對齊後端實際三態（凱莉 fulilian-backend）
export type EventStatus = 'pending' | 'in_progress' | 'resolved';

export const STATUS_LABEL: Record<EventStatus, string> = {
  pending: '待處理', in_progress: '處理中', resolved: '已結案',
};

// 事件類型：fall＝跌倒偵測；hazard＝物件偵測（系統抓到危險物品，UI 以「潛在危險」標示）。
// 顯示文字一律走 EVENT_TYPE_LABEL，元件外禁止另寫死「跌倒」等字樣。
export type EventType = 'fall' | 'hazard';
export const EVENT_TYPE_LABEL: Record<EventType, string> = {
  fall: '跌倒',
  hazard: '潛在危險',
};

// 潛在危險（物件偵測）可辨識的危險物品類型；跌倒事件此欄為 null。
export type HazardObject = '刀具' | '熱源' | '藥品' | '玻璃碎片' | '積水' | '其他';
export const HAZARD_OBJECTS: HazardObject[] = ['刀具', '熱源', '藥品', '玻璃碎片', '積水', '其他'];

// 通報狀態：獨立於事件生命週期 status（pending/in_progress/resolved）之外的上報流程追蹤。
// 初報→續報→結報。null＝尚未通報。
// ⚠ 通報單本身已存後端（見 api/reports.ts），但 detect_events 沒有 report_stage 欄位，
//   故事件的通報狀態仍由前端記憶體維護（重整會歸零）；後端補欄位後改由事件 payload 帶入。
export type ReportStage = 'initial' | 'follow_up' | 'final';

export const REPORT_STAGE_LABEL: Record<ReportStage, string> = {
  initial: '已初報', follow_up: '已續報', final: '已結報',
};

// 通報狀態按鈕依此順序呈現，元件外禁止另寫死順序。
export const REPORT_STAGES: ReportStage[] = ['initial', 'follow_up', 'final'];

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

// ── 生成通報單（IA：生成通報單頁）───────────────────────────────────────
// 官方長照事件通報單欄位。選項清單集中此處，禁止散落各元件硬編碼。
export type ReportGender = '男' | '女';
export const REPORT_GENDERS: ReportGender[] = ['男', '女'];

export type ReportWelfare = '低收入戶' | '中低收入戶' | '一般戶';
export const REPORT_WELFARE_OPTIONS: ReportWelfare[] = ['低收入戶', '中低收入戶', '一般戶'];

export const REPORT_DISTRICTS = [
  '南港區', '內湖區', '中正區', '萬華區', '大安區', '松山區',
  '文山區', '信義區', '士林區', '北投區', '中山區', '大同區',
] as const;
export type ReportDistrict = (typeof REPORT_DISTRICTS)[number];

export type ReportLocation = '案家' | '案家附近' | '醫院' | '陪同外出活動途中' | '其他';
export const REPORT_LOCATIONS: ReportLocation[] = [
  '案家', '案家附近', '醫院', '陪同外出活動途中', '其他',
];

// 影響程度：有傷害（分五級）或無傷害。每項附官方說明文字。
export type ReportImpact = '有傷害' | '無傷害';
export type ReportInjuryLevel = '死亡' | '極重度' | '重度' | '中度' | '輕度';
export const REPORT_INJURY_LEVELS: { value: ReportInjuryLevel; desc: string }[] = [
  { value: '死亡', desc: '個案死亡。' },
  { value: '極重度', desc: '個案永久性殘障或永久性功能障礙（如肢障、腦傷等）。' },
  {
    value: '重度',
    desc: '個案除需額外的探視、評估或觀察外，還需手術、住院或延長住院處理（如骨折或氣胸等需延長住院）。',
  },
  {
    value: '中度',
    desc: '個案除需額外的探視、評估或處置，如量血壓、脈搏、血糖之次數比平常之次數多，照X光、抽血、驗尿檢查或包紮、縫合、止血治療、1~2 劑藥物治療。',
  },
  {
    value: '輕度',
    desc: '事件雖然造成傷害，但不需或只需稍微處理，不需增加例行照護。如表皮泛紅、擦傷、瘀青等。',
  },
];
export const REPORT_NO_INJURY_DESC = '事件發生在個案身上，但是沒有造成任何的傷害。';

export const REPORT_SERVICE_PERSONNEL = [
  '專業人員', '居服員', '交通接送提供人員', '喘息服務提供人員', '輔具評估人員', '其他',
] as const;
export type ReportServicePersonnel = (typeof REPORT_SERVICE_PERSONNEL)[number];

// 通報別（表單最上方，單選）：本次通報屬初報／續報／結報。
export const REPORT_TYPES = ['初報', '續報', '結報'] as const;
export type ReportType = (typeof REPORT_TYPES)[number];

// 通報別 → 事件通報狀態的唯一對照。儲存通報單時依此把表單 reportType 轉成事件 report_stage，
// 禁止在元件內散落硬編碼（配合 REPORT_STAGE_LABEL：initial→已初報／follow_up→已續報／final→已結報）。
export const REPORT_TYPE_TO_STAGE: Record<ReportType, ReportStage> = {
  初報: 'initial',
  續報: 'follow_up',
  結報: 'final',
};

// 七、事件內容（一）服務過程（可複選）
export const REPORT_SERVICE_PROCESS = [
  '送醫事件', '照顧意外事件', '藥物事件', '治安事件',
  '傷害行為事件', '公共意外', '違反專業倫理守則者', '其他',
] as const;
export type ReportServiceProcess = (typeof REPORT_SERVICE_PROCESS)[number];

// 七、事件內容（二）不限服務時段，知悉時即通報（可複選）
export const REPORT_IMMEDIATE_NOTIFY = [
  '家庭暴力事件暨性侵害責任通報', '自殺（含意圖）、自傷事件', '傳染病通報',
] as const;
export type ReportImmediateNotify = (typeof REPORT_IMMEDIATE_NOTIFY)[number];

// 九、此事件發生後的立即處理（可複選）。'無介入' 另有子選項見 REPORT_NO_INTERVENTION。
export const REPORT_HANDLING = [
  '無介入', '送醫治療', '予以病人家屬慰問及支持', '通報警政機關',
  '已於24小時內完成家庭暴力暨性侵害事件責任通報', '已通報自殺防治中心', '其他',
] as const;
export type ReportHandling = (typeof REPORT_HANDLING)[number];

// 九、「無介入」的子選項（可複選）
export const REPORT_NO_INTERVENTION = ['不需任何處理', '病人拒絕處置', '其他'] as const;
export type ReportNoIntervention = (typeof REPORT_NO_INTERVENTION)[number];

// 通報單表單狀態。日期與地點於進頁時由事件自動帶入，其餘手填（事件無個案主檔資料）。
export interface ReportFormData {
  reportType: ReportType | null;
  caseName: string;
  caseIdNumber: string;
  gender: ReportGender | null;
  birthday: string;
  welfare: ReportWelfare | null;
  eventYear: string;
  eventMonth: string;
  eventDay: string;
  eventHour: string;
  eventMinute: string;
  district: ReportDistrict | null;
  location: ReportLocation | null;
  locationNote: string;
  impact: ReportImpact | null;
  injuryLevel: ReportInjuryLevel | null;
  serviceUnit: string;
  servicePersonnel: ReportServicePersonnel[];
  servicePersonnelNote: string;
  // 七、事件內容
  serviceProcess: ReportServiceProcess[];
  serviceProcessNote: string;
  immediateNotify: ReportImmediateNotify[];
  // 八、事發經過說明
  eventNarrative: string;
  // 九、立即處理
  handling: ReportHandling[];
  handlingNote: string;
  noIntervention: ReportNoIntervention[];
  noInterventionNote: string;
  // 十、通報者資料
  reporterName: string;
  reporterUnit: string;
  reporterTitle: string;
  // 十一、通報日期（進頁自動帶入當下時間）
  reportYear: string;
  reportMonth: string;
  reportDay: string;
  reportHour: string;
  reportMinute: string;
}

// 已儲存的通報單。走真後端 GET /events/{id}/reports（見 api/reports.ts）。
// 後端另有 report_id 與 created_by（通報人員編），前端目前無顯示處故未帶入。
export interface SavedReport {
  eventId: string;
  form: ReportFormData;
  savedAt: string; // ISO，儲存當下時間
}

// 警示處理紀錄（首頁右側 log）：每則全螢幕警示被「接手」／標記「誤報」，或偵測到潛在危險，轉成一筆 log。
export type AlertLogAction = 'acknowledged' | 'false_alarm' | 'hazard_detected';
export const ALERT_LOG_ACTION_LABEL: Record<AlertLogAction, string> = {
  acknowledged: '接手', false_alarm: '誤報', hazard_detected: '潛在危險',
};

export interface AlertLogEntry {
  id: string;
  eventId: string;
  cameraName: string;   // 事發鏡頭：區域（名稱）
  action: AlertLogAction;
  hazardObject: HazardObject | null; // hazard_detected 才有值，其餘 null
  at: string;           // ISO，處理當下時間
}

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
  stream_source: StreamSource; // 畫面渲染來源；本輪 mock 資料一律為 null，見 CameraDetailModal 渲染分支
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
  event_type: EventType;
  hazard_object: HazardObject | null; // 潛在危險偵測到的物品類型；跌倒事件為 null
  camera: Camera;
  occurred_at: string;       // ISO
  status: EventStatus;
  report_stage: ReportStage | null;  // 通報狀態（初報/續報/結報）；null＝尚未通報。demo 前端維護，見 REPORT_STAGE_LABEL
  confidence: number;        // YOLO 初篩
  vlm_result: VlmResult | null;  // ★ null＝YOLO 高分直通，UI 需顯示「YOLO 高信心直通」且不得噴錯
  verdict: EventVerdict;     // 判定結果，'false_alarm'＝誤報，UI「誤報」標籤依此判斷（非 status）
  false_alarm_label: FalseReportLabel | null;  // 標記誤報時選的類型（坐地/伸展…）；非誤報為 null。誤報紀錄詳情頁「事件」欄顯示此值
  false_alarm_note: string | null;   // 標記誤報時填的備註（選填）；空白或非誤報為 null。誤報紀錄詳情頁「備註」欄顯示此值
  clip_path: string | null;      // ← 事件影片片段路徑，詳情頁播放器用
  snapshot_path: string | null;  // ← 事件快照圖片路徑，卡片縮圖／彈窗用
  assignee: string | null;
  notified_to: string | null;
  ack_deadline: string | null;   // 接手時限（ISO），pending 時有值，用於逾時倒數
  resolve_deadline: string | null; // 接手後須結案的 24 小時時限（ISO）；接手當下寫入＝now+24h，null＝尚未接手。每筆各自獨立
  follow_up_deadline: string | null; // 續報期限（ISO）：初報起算 5 個工作日（排除週末），未初報＝null。以日期顯示，非倒數
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

// 時間區間下拉：對應聚合粒度（≤24h 原始15分級距／1–7天每小時最低分／>7天每日最低分，皆取最低分非平均）。
export type EnvHistoryRange = 'today' | '7d' | '30d' | 'custom';

export interface KpiSummary {
  pending_events: number;
  false_positive_rate: number;
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
export interface AuthSession { token: string; role: Role; display_name: string; must_change_password: boolean; }
export interface AuthProvider {
  requestCode?(email: string): Promise<void>;
  verifyCode?(email: string, code: string): Promise<AuthSession>;
  loginWithPassword?(employeeId: string, password: string): Promise<AuthSession>;
  logout(): void;
}

// 角色顯示文字（管理使用者頁、UserMenu 共用），元件外禁止另寫死。
export const ROLE_LABEL: Record<Role, string> = {
  admin: '系統管理者',
  staff: '護理站值班人員',
};

// 管理使用者頁（🔒 admin-only）：demo 以假資料呈現。密碼為 write-only，不納入本型別。
// 後端 /users 就緒後改由 API 下發（密碼一律後端雜湊，前端不留存）。
export interface ManagedUser {
  id: string;
  name: string;
  employee_code: string; // 工號
  role: Role;
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

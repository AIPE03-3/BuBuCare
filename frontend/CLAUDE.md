## 專案規格文件（自動載入）

- 專案總覽：@docs/現行規格/00_專案總覽.md
- IA 導覽架構：@docs/現行規格/01_IA導覽架構.md
- 需求規格速查：@docs/現行規格/02_需求規格速查.md
- 畫面規格決策：@docs/現行規格/03_畫面規格_各頁最終決策.md
- 後端落差記錄：@docs/現行規格/04_後端現況與規格落差.md（⚠ 動工前必看）

決策歷程（僅追溯用，平常不需讀）：docs/決策歷程/

# CLAUDE.md — Fulilian 中控台前端開發規範

本檔為專案唯一權威規範。每次動工前先完整閱讀本檔；任何實作與本檔衝突時，以本檔為準並停下來詢問，不得自行變更規範。

## 專案概述

長照機構跌倒偵測中控台（React SPA）。使用者為護理站值班人員與系統管理者。最高原則：**降低值班人員認知負荷**——每張卡片只有一個視覺重點、紅色只出現在真正危險的資訊上、不做花俏動畫（僅允許 150ms 透明度／背景色過渡）。本階段為 MVP demo：畫面優先、資料全部走 mock，但架構必須可無痛接真後端。

## 技術堆疊

- Vite + React 18 + TypeScript（專案已建立，勿重建）
- Tailwind CSS v4（@tailwindcss/vite 外掛）+ CSS variables design tokens
- react-router v6、Recharts
- 語言：一律繁體中文（台灣用語），禁止簡體字與中國用語
- 字型：Noto Sans TC

## 四條鐵律（違反即重做）

1. 元件內**禁止直接 fetch／axios**，資料一律經 `src/api/` 取得。
2. **禁止寫死色碼**（hex、rgb、Tailwind 色名如 red-500 皆禁止），顏色一律引用 tokens 變數。
3. 事件狀態顯示文字一律走 `STATUS_LABEL` 對照表，禁止散落硬編碼。
4. 登入相關元件**禁止 import 具體 auth provider**，只能經 `src/api/auth/index.ts`。

## 資料夾結構

```
src/
├─ api/
│  ├─ client.ts            # fetch 封裝，baseURL 吃環境變數
│  ├─ events.ts  kpi.ts
│  ├─ auth/
│  │  ├─ index.ts           # 依 AUTH_MODE 匯出 provider
│  │  ├─ emailOtp.ts        # 本期實作
│  │  └─ employeePassword.ts# 空殼（介面已定，throw 尚未啟用）
│  └─ mock/                 # 假資料，日後整包刪除
├─ config/app.ts            # THEME / AUTH_MODE / FORGOT_PASSWORD_ENABLED
├─ hooks/                   # useAuth / useEventSocket
├─ components/              # 共用元件
├─ pages/                   # Login / Home / 其餘空殼頁
├─ types/index.ts           # 全部型別集中此檔
└─ styles/tokens.css
```

## Design Tokens（styles/tokens.css）— 配色方案 A：專業療癒風

語意色是功能訊號，獨立於品牌色之外、永遠滿飽和；品牌色只管氛圍（60% 主色背景／30% 輔色側欄／10% 點綴強調）。

```css
:root {
  /* 語意色：狀態標籤、警示、趨勢色點專用，禁止挪作裝飾 */
  --danger:  #C62828;  --danger-bg:  #FADCDC;  /* 危險／已升級／發送失敗 */
  --warning: #D97706;  --warning-bg: #FCEBD3;  /* 警示／待處理／逾時 */
  --success: #1B7F4D;  --success-bg: #D7EDDD;  /* 良好／已接手／已結案 */
  --offline: #6B7280;                           /* 離線／誤報：灰字空心外框 */
  --info:    #2F4A7A;                           /* 保留，用途待定（原新事件提示條已移除；候選：列管 REGULATED 狀態色，動工時定案） */
}
.theme-care-a {
  --bg-base:      #EFF5EF;  /* 60% 淡綠底 */
  --bg-surface:   #FFFFFF;  /* 卡片 */
  --bg-surface-2: #ECE9F7;  /* 30% 淡紫：側欄、表頭、次要區塊 */
  --border:       #D8E0D8;
  --text-primary:   #2C3E50;
  --text-secondary: #5D6B7A;
  --text-muted:     #8A97A5;
  --brand:        #46785F;  /* 10%：選中態、連結、中性主鈕 */
  --brand-soft:   #DCE9E0;
  --notice:       #7A5C00;  --notice-bg: #F5E6B8; /* 僅限未讀／待辦等非緊急徽章 */
}
```

配色使用規則：

- `<html class="theme-care-a">`，由 `config/app.ts` 的 THEME 控制。
- **具語意的按鈕永遠用語意色**：「確認前往處理」＝ `--success` 填色白字；「結案」＝ success 外框；「標記誤報」＝ offline 外框。`--brand` 只給中性操作（登入、下載、載入更多、審核並存檔）。
- `--notice` 淡黃徽章嚴禁用於跌倒／危險／逾時（那是 warning／danger 的地盤）。
- 淡色背景禁止白色文字；文字對背景對比 ≥ 4.5:1。

## 狀態標籤配色（StatusTag 元件內建，元件外禁止覆寫）

| 待處理 pending     | --warning-bg 底＋橘字，可附「逾時 m:ss」倒數 |
| 處理中 in_progress | 深色外框、透明底                            |
| 已結案 resolved    | --success-bg 底＋綠字                        |
| 誤報（verdict=false_alarm）／離線 | 灰字、空心外框、無底色         |

字級：頁標 20px／卡標 16px／內文 14px／輔助 12px／KPI 大數字 40px。

## 核心型別（types/index.ts，全案唯一定義處）

```ts
// MVP：對齊後端實際三態（凱莉 fulilian-backend）
export type EventStatus = 'pending' | 'in_progress' | 'resolved';

export const STATUS_LABEL: Record<EventStatus, string> = {
  pending: '待處理', in_progress: '處理中', resolved: '已結案',
};

// 誤報非獨立狀態，改由 verdict 判斷（後端：誤報＝verdict false_alarm 且直接 resolved）
export type EventVerdict = 'true_alarm' | 'false_alarm' | null;

// 後續（非 MVP，後端就緒後再開）：
//   狀態預留 'NOTIFIED' | 'ACKNOWLEDGED' | 'ESCALATED' | 'SUPPRESSED'
//   逾時升級 UI、已升級篩選，皆待後端補齊再實作

export type DeviceStatus = 'online' | 'offline' | 'disabled';
// online=正常運作／offline=暫時離線（監控死角，需注意）／disabled=永久已停用（排除總覽查詢）
// 後端 devices.status 已確認為三態（active/inactive/fault），對照表在 api/cameras.ts 的 STATUS_MAP

export interface Camera {
  id: number;
  name: string;              // 鏡頭5
  zone: string;              // 活動室A（區域分組，無樓層層）
  floor: string | null;      // demo 一律不顯示
  // 兩條完整的 WHEP 網址，由後端把資料庫的頻道名接上 .env 的 MEDIAMTX_BASE_URL 組成。
  // null＝這個環境沒有這條串流（後端沒設位址，或這台鏡頭沒填該頻道）。
  stream_url: string | null;        // 即時（原味）
  stream_url_detect: string | null; // 偵測（AI 畫框後），沒接 AI 的鏡頭為 null
  // 頻道名（cam_in / phone_a…），與上面兩條網址一一對應、同時有值或同時為 null。
  // 用途：向後端 POST /streams/{channel}/token 換 60 秒串流權杖再去連 MediaMTX。
  stream_channel: string | null;
  stream_channel_detect: string | null;
  status: DeviceStatus;      // 取代原本 online: boolean，支援離線/已停用分開判斷
}
// 已移除 StreamSource 型別：全站零讀取，且與 stream_url_detect 語意重疊。

export type EnvSafetyGrade = '良好' | '注意' | '警示' | '危險';
// 對照 02檔：total_score 90-100良好／70-89注意／40-69警示／0-39危險

export interface EnvSafetyScore {
  score_id: string;
  device_id: number;
  total_score: number;       // 0-100，四向度加總（地面30/通道30/危險物品20/照明20，2026-07-12定案）
  grade: EnvSafetyGrade;     // 前端依 total_score 對照門檻算出，非後端原始欄位
  score_drop: number | null; // 較前次變化；null＝無前次可比較（如離線後首筆）
  assessed_at: string;       // ISO
}

export interface VlmResult {
  confidence: number;
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
  ack_deadline: string | null;   // 接手時限（ISO），NOTIFIED 時有值，用於逾時倒數
  escalated_to: string | null;   // 升級通知對象；待班表系統導入後帶入實際值班人員，demo 暫以當日值班組長代替
  alerted_at: string | null;     // 曾以全螢幕警示呈現的時間（ISO），用於「⚠ 曾全螢幕警示」持久徽章
  stage_latency_ms?: { capture: number; inference: number; emit: number }; // 預留，本期不顯示
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

export interface KpiSummary {
  pending_events: number;
  false_positive_rate: number;
  env_score_avg: number;
  env_score_threshold: number;   // 低於此值數字轉 --danger
  hnp_count: number;
  hnp_threshold: number;         // 達標數字轉 --warning
}

export type Role = 'admin' | 'staff';
export interface AuthSession {
  token: string;
  role: Role;
  display_name: string;
  must_change_password: boolean; // 新帳號首次登入／被 admin 重設密碼者為 true，觸發強制改密碼流程
  // employee_code: string | null — 待凱莉確認後端欄位與 /me 端點後新增，未確認前不得實作
}
export interface AuthProvider {
  requestCode?(email: string): Promise<void>;
  verifyCode?(email: string, code: string): Promise<AuthSession>;
  loginWithPassword?(employeeId: string, password: string): Promise<AuthSession>;
  logout(): void;
}

export type NotificationChannel = 'web_push'; // MVP 僅一種，UI 用下拉不寫死文字，預留未來擴充（8-6 通報管道）
export const CHANNEL_LABEL: Record<NotificationChannel, string> = { web_push: 'Web Push' };

export type NotificationStatus = 'delivered' | 'failed';
export const NOTIFICATION_STATUS_LABEL: Record<NotificationStatus, string> = {
  delivered: '已送達', failed: '發送失敗',
};

export interface NotificationRecord {
  id: string;
  event_id: string;
  channel: NotificationChannel;
  sent_at: string;
  status: NotificationStatus;   // 'delivered' | 'failed'，不含失敗原因
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
```

## 權限規則

- role 取自登入 session：`admin` 或 `staff`。
- staff：側欄「MLOps 面板」「設定」兩個節點**完全不渲染**（不是灰階不可點）；路由 /mlops、/settings 包 RequireAdmin。
- 「Agent 洞察」節點：所有角色皆灰階不可點，右側小字「即將推出」。

## 後端銜接注意（demo 用 mock，但介面照此設計）

- 事件有兩條產生路徑：YOLO 高信心直通（`vlm_result: null`）與 VLM 複判後產生。所有顯示 VLM 資訊的地方都必須處理 null。
- 即時推播經 `useEventSocket` hook（demo 用計時器模擬），介面比照 WebSocket，日後直接替換連線實作。
- 即時影像**已接真串流**（WebRTC/WHEP，見 `components/LiveStream.tsx`）：首頁四宮格與鏡頭彈窗皆播放實際畫面，網址由 `GET /devices` 提供（`stream_url`＝即時、`stream_url_detect`＝AI 偵測）。網址為 null 時才退回灰色占位框（`CAMERA_LABEL.LIVE_PLACEHOLDER`）。事件／偵測紀錄的截圖仍是「事件快照（影像片段）」（`SNAPSHOT_PLACEHOLDER`），兩者語意不同、不共用文字。
- **串流已有身分驗證，光有網址看不到畫面**：`LiveStream` 連線前必須先以 `fetchStreamToken(channel)` 向後端換一張 60 秒串流權杖，帶 `Authorization: Bearer` 打 WHEP，MediaMTX 會回頭向後端驗票。故 `LiveStream` 的 `whepUrl` 與 `channel` 兩個 prop **必須是同一個模式的一組**（同為即時或同為偵測），配錯會 401。

## Definition of Done（每個任務完成前自查）

- `npm run build` 與 ESLint 全數通過
- 全案 grep 不到寫死色碼與 Tailwind 色名
- 新增元件皆引用 types/index.ts，無重複型別定義
- 畫面文字無簡體字
- 本輪若有規格變更（新狀態、新欄位、新配色語意），檢查本檔的型別定義、
  STATUS_LABEL、狀態標籤配色表是否需同步更新，未同步不得 commit

# 整合 `origin/albert_chiang` 的技術（2026-07-31）

分支：`feat/merge-albert-mlops-pose`（從 `feat/mvp-full-chain` 開出）

兩條線在 2026-07-24（`b9d6844`）分岔，之後各自走了 122 / 71 個 commit。**沒有用 merge**，
是逐項挑檔案重寫——因為兩邊在後端架構與推論架構上是相反方向（見第四節）。

---

## 一、整合了什麼

### 1. 平衡抽樣：Stratified Split by Rarest Class

**改** [`ai/prepare_dataset.py`](../ai/prepare_dataset.py)（新參數 `--split-strategy`，預設 `balanced`）

本專案的類別分佈很偏（實測 tv 179 個框、sofa 只有 5 個）。純隨機切 80/20 時，只出現在
5 張圖裡的 sofa 很可能整組落在 train（機率約 0.8⁵≈33%）或整組落在 val：前者讓 val
評估不到這個類別、mAP 虛高；後者讓模型根本沒學過它，那一類必定 0 分。

做法：統計每個類別出現在幾張圖 → 每張圖的「主類別」＝它含有的類別中全域最稀有的那個
→ 依主類別分組，每組各自切 80/20。

**與上游的四處差異**（都寫在該檔的檔頭）：

| | 上游 | 這裡 | 為什麼 |
|---|---|---|---|
| seed | 每組換一次（`42 + p_cls`）| 單一 seed 打亂已排序清單 | `dataset_splits/` 進版控，要換機器可重現 |
| 取整 | `int(len * 0.8)` | `round()` + 每組至少留 1 張給 train | 上游對「只有 1 張圖的組」會切成 train=0/val=1，**最稀有的類別反而完全沒進訓練集**，正好打死這個演算法要解的問題 |
| 空標註圖 | 未處理 | 清洗階段就隔離掉 | — |
| 「稀有」怎麼算 | 總共幾個框 | **幾張圖含這個類別** | 切分切的是圖。一個類別就算有 100 個框、全擠在 2 張圖裡，隨機切照樣可能整組落到同一邊；按框數算會誤判成常見類別而不去保護它 |

> ⚠️ 切分策略換了，[`ai/MLOPS.md`](../ai/MLOPS.md) 記錄的 mAP50=0.9912 是用舊切分跑的。
> 要重現那個數字請加 `--split-strategy random`。

### 2. YOLO-Pose 這條重訓線（原本只有 RT-DETR）

新增四個檔、改兩個：

| 檔案 | 做什麼 |
|---|---|
| [`ai/pose_data.yaml`](../ai/pose_data.yaml) | 新增。`nc: 1` + `kpt_shape: [17,3]` + `flip_idx` |
| [`ai/prepare_dataset.py`](../ai/prepare_dataset.py) | 加 `--task pose`：保留 17 關節點清成 56 欄 |
| [`ai/pose_to_labelstudio_sdk.py`](../ai/pose_to_labelstudio_sdk.py) | 新增。骨架預標註**雙向**同步 |
| [`ai/clearml_pose_train_pipeline.py`](../ai/clearml_pose_train_pipeline.py) | 新增。滾動式重訓 |
| [`ai/labelstudio_client.py`](../ai/labelstudio_client.py) | 新增。抽出兩支同步腳本共用的 LS 管線 |
| [`ai/submit_task.py`](../ai/submit_task.py) | 加 `--task pose`，兩條線共用同一套排隊邏輯 |

整條鏈：

```
邊緣端快照 → Label Studio（KeyPointLabels 專案）→ AI 預標註（框＋17 點）
                                                        │
                                                人工審核 / 修正 / Submit
                                                        │
                        active_learning_dataset/pose_labels/
                                                        │
                        prepare_dataset.py --task pose  →  ai/pose_dataset/
                                                        │
                        clearml_pose_train_pipeline.py（繼承 best → 訓練 → 評估 → 標 best）
```

**比上游多做的**：

- **上游的 `pose_to_labelstudio_sdk.py` 是單向的**（只推預標註，沒有把人工標註拉回本地的
  路徑），所以它產不出訓練資料。這裡補上回收方向，鏈才閉合。
- **預標註同時推框與關節點**。上游只推 keypointlabels，但 YOLO-Pose 的標註格式是
  「框 + 掛在框上的關節點」，少了框湊不出訓練標籤。
- **關節點名稱與 Label Studio 介面對帳**，對不上直接停。上游照 `KPT_NAMES` 硬推，
  介面標籤名不同時 Label Studio 會收下 200 但畫面不顯示，看起來像沒推成功。
- **門檻看 pose mAP50，不是 box mAP50**。框準但關節點全錯的模型對跌倒判定沒用，
  而 box mAP 幾乎一定比 pose 高，拿它對門檻等於門檻形同虛設。
- **兩道關卡才標 best**：過絕對門檻 **且** 不比上一輪差。上游只有「打擂台」而且是
  `>=`，冷啟動那輪 `old_map50=0`，任何垃圾都會過（RT-DETR 那條實測踩過）。
- **模型標籤是 `["yolo","pose","best"]` 三個一組**。與 RT-DETR 共用同一個 ClearML 專案，
  只靠 `best` 一個標籤會讓下一輪把 RT-DETR 的權重餵給 YOLO-Pose。

**人工標註怎麼還原成「某個人的 17 個關節點」**：Label Studio 的 keypoint 各自獨立，
不會告訴你哪幾點屬於同一個人。這裡用「關節點落在哪個框裡」還原，每個點指派給包含它的
**最小面積**框。⚠️ 兩個人重疊時，落在交集區的點會被指派給比較小的那個框——本專案的
俯視公共區域場景夠用，要標密集人群得改用 Label Studio 的 region grouping。

### 3. 前端骨架疊圖改成 canvas（取代 `detect_publisher`）

| | 舊：`ai/detect_publisher.py`（已刪）| 新 |
|---|---|---|
| 疊圖在哪 | AI 端，燒進畫面 | 瀏覽器 canvas |
| AI 端成本 | 每路多一支 ffmpeg 做即時編碼 | 一次幾 KB 的 JSON POST |
| 切換即時／偵測 | 換一條串流網址，要重新協商 WebRTC，畫面黑一下 | 只是多疊一層 canvas，影像不斷 |
| NO_RENDER=1 時 | 沒畫面可推，只能停用 | 照常（座標來自幾何判定，跟畫不畫圖無關）|
| 用 VLC 等外部播放器 | 看得到框 | **看不到**（框不在影像裡）← 換過來的代價 |

改動的檔案：

- 刪 `ai/detect_publisher.py`；新增 [`ai/detection_broadcaster.py`](../ai/detection_broadcaster.py)
- [`ai/inference_test.py`](../ai/inference_test.py)：新增 Step E 送座標，拆掉 `detect_url` 整條線
- [`ai/backend_devices.py`](../ai/backend_devices.py)：移除已無人使用的 `build_detect_channels`
- 新增 [`backend/streams/detections.py`](../backend/streams/detections.py) 與 15 則測試
- 新增 [`frontend/src/api/detections.ts`](../frontend/src/api/detections.ts)、
  [`frontend/src/components/SkeletonOverlay.tsx`](../frontend/src/components/SkeletonOverlay.tsx)
- 改 `LiveStream.tsx`（新 prop `overlayDeviceId`）、`Home.tsx`、`CameraDetailModal.tsx`
- `.env.example`：`DETECT_STREAM*` 四個鍵 → `DETECT_BROADCAST*` 三個鍵

**契約**（`POST /streams/detections`）：

```jsonc
{
  "device_id": 301,            // 前端就是靠這個對回 Camera.id
  "camera_id": "Room_301_Bed", // 只給人看 log
  "persons": [{
    "bbox": [0.1, 0.2, 0.3, 0.6],  // x1,y1,x2,y2，全部 0..1 的比例值
    "conf": 0.91, "is_fall": false, "track_id": 7,
    "kps": [[0.15, 0.25], /* …共 17 組，0..1 */]
  }],
  "seq": 42
}
```

`device_id` 由 AI 端用**與 Kafka 事件完全相同**的換算產生（挖出 `camera_id` 裡的所有
數字），前端因此不必知道 `Room_301_Bed` 這個字串格式。

---

## 二、踩到的雷與處置

| # | 雷 | 處置 |
|---|---|---|
| 1 | 🔴 **Discord webhook token 寫死在原始碼**。`clearml_train_pipeline.py:225` 與 `clearml_pose_train_pipeline.py:215` 都把一組**可用的** webhook 寫成 `os.getenv` 的預設值 | 改成沒設 `DISCORD_WEBHOOK_URL` 就不通知，**不留任何預設值**。**⚠️ 待辦：請 albert 去 Discord 重新產一組**——那組已經在遠端分支的歷史裡，換分支也拿得到 |
| 2 | 🔴 **`/events/live-detection` 兩個端點完全沒有驗證**。POST 誰都能推假的跌倒骨架、GET SSE 帶 `Access-Control-Allow-Origin: *` 誰都能讀即時人體座標 | POST 走 `X-API-Key`（與 `POST /events` 同一把）、GET 走登入 token，並**額外擋掉 `scope=stream` 的短命串流權杖**（那種票會被寫進 MediaMTX 與 nginx 的存取紀錄，敏感度不同）。三則測試把兩道門釘住 |
| 3 | 🟡 **座標型別自相矛盾**。上游 `CameraStream.tsx` 的介面註解寫「像素座標 x1 y1 x2 y2」，畫的時候卻乘上畫布寬高當比例用——換一台不同解析度的鏡頭就會畫歪 | 契約定死**一律 0..1 正規化**，寫進 `Person` 的 docstring 與前端型別 |
| 4 | 🟡 **無界佇列接高頻座標**。上游直接用 `asyncio.Queue()`；只要一條連線卡住（分頁切到背景、網路變慢），佇列會一路長大到吃光記憶體，而且不報錯 | 自己開**有界、滿了丟最舊**的轉播池（深度 3），沒共用 `events/sse.py` 那個給警報用的無界池。有測試釘住 |
| 5 | 🟡 上游前端 SSE payload 的 key 是硬寫的（`data['1'] \|\| data['Room_301_Bed'] \|\| data.persons`），AI 端也照樣送三份重複資料 | 契約只有一份，`device_id` 對應 |
| 6 | 🟡 上游 `CameraStream.tsx` 全是硬寫的 `#00ff88` / `#ff334b` 等色碼，違反前端鐵律二 | 顏色全走 design tokens（`resolveCssVar`），跌倒 `--danger`、正常 `--success`、骨線 `--brand` |

---

## 三、沒做的，與為什麼

### 三項「本來以為要做」的，這個分支早就有了

| 項目 | 現況 |
|---|---|
| `clean_pose_to_det.py`（pose 標註降維成偵測框）| 就是 [`ai/prepare_dataset.py`](../ai/prepare_dataset.py)，而且多三道檢查（會擋掉 21 個檔的寫死假 pose 標註，上游的「無條件截前 5 欄」會把它們變成看起來合理但捏造的框）|
| ONNX IR version 降級到 8（相容 Triton）| [`ai/export_models.py:208`](../ai/export_models.py#L208) 已經有 |
| albert 的 RT-DETR 重訓 pipeline | `ai/clearml_train_pipeline.py` 的檔頭就寫「移植自 albert_chiang」，先前已移植 |

### 刻意不做的

- **`deepstream_configs/deepstream_app_config.txt`**（DeepStream 7.0）：設定寫得完整
  （nvinferserver 接 Triton、NvDCF tracker、RTSP sink、Kafka broker），但它引用的
  `config_infer_triton.txt` **在 repo 裡不存在**，目前是無法執行的骨架。
- **`rtdetr-l-deim.yaml`**（DEIM 版 RT-DETR 骨幹）：`nc: 3`（person/bed/wheelchair），
  與本專案 `data.yaml` 的 5 類對不上；而且我們的訓練是從 `rtdetr-l.pt` **繼承權重**，
  用 yaml 從零建模型跟滾動式重訓的設計衝突。
- **`start_edge.sh` / `start_cloud.sh`**：全是硬寫的 `localhost` 與 `Fall/.venv` 路徑，
  與本專案的 docker-compose 部署衝突。裡面的 ffmpeg 踩坑參數（`-nostdin`、
  `-tune zerolatency -g 30`、Iriun 的 `uyvy422 60fps`）有參考價值，記在這裡備查。
- **`CctvGridTile.tsx` 九宮格電視牆**：純 UI，與本次的技術整合無關，要做可另開。

### 明確**不能**跟著合的退版

albert 那條分支同時做了幾件把本分支往回推的事，一項都沒有帶進來：

| 項目 | 狀況 |
|---|---|
| `backend/auth.py`、`models.py`、`database.py`、`sse.py`、`event_routes.py`、`event_service.py`、`security.py`、`dependencies.py` | **舊扁平架構被復活**。分岔點時這些早已重構進 `core/`、`events/`、`users/`；他在 `0e5d2cd` 整包蓋回來，之後又疊了一堆 `try: from backend.core… except ModuleNotFoundError: from core…` 的雙路 import 補丁 |
| `backend/core/config.py` | JWT 從 8 小時**退回 1 天**、拿掉 `SSL_ROOT_CERT`、`DB_USER` 不再 `quote_plus` |
| `.github/workflows/` | 被 `5e9fc4f` 整個刪除 |
| `scripts/check_guardrails.py`、`.githooks/` | 完全不存在 |
| `agent/`（36 檔）| 完全不存在 |
| 多人追蹤 | 他改用 ultralytics 本機 `.track()`，**沒走 Triton**（純本機 pipeline）。本分支的 ByteTrack 吃 Triton 偵測結果 + 逐人狀態機 + 發報去重是往前的方向 |
| 版控裡的執行期資料 | `label_studio.sqlite3`(7MB)、261 張 snapshot jpg、`backend/aidb.sqlite`、`jmx_prometheus_javaagent.jar`(10MB) |

---

## 四、驗證

| 項目 | 結果 |
|---|---|
| 護欄 `scripts/check_guardrails.py` | ✅ 通過（317 檔）|
| 後端全套 pytest | ✅ **191 passed**（新增 15 則）|
| 前端 `npm run build` | ✅ 通過 |
| 前端 ESLint `--max-warnings=0` | ✅ exit 0 |
| 前端鐵律二（寫死色碼）| ✅ 新檔全走 tokens |
| 清洗與平衡抽樣邏輯 | ✅ 逐項驗過：56 欄輸出、假 pose 兩種模式都丟、關節點數檢查、非 person 過濾、座標夾回、同 seed 可重現、單張圖的組全進 train |
| pose 標註回收 → 清洗 | ✅ 端到端對帳：自己產的標籤能通過自己的清洗 |
| AI 端 payload → 後端契約 | ✅ 對帳通過（含無 tracker、無骨架、無人幀三種邊界）|

**沒有做的驗證（要在有硬體/服務的機器上補）**：

- YOLO-Pose 實際重訓（本機 `active_learning_dataset/labels/` 14 個檔**全是 5 欄偵測標註**，
  `--task pose` 實跑是 144 行全丟、可用圖片 0 —— 見下方待辦）
- `POST /streams/detections` 的端到端（要 AI 端 + 後端 + MediaMTX 同時在跑）
- 前端骨架疊圖的實際畫面

---

## 五、接手待辦

1. **🔴 請 albert 重新產一組 Discord webhook**（舊的已在版控歷史裡）。
2. **YOLO-Pose 這條線目前沒有資料可吃。** 要先在 Label Studio 開一個帶
   `<KeyPointLabels>` 與 `<RectangleLabels>` 的專案、設 `LS_POSE_PROJECT_ID`，
   跑 `python ai/pose_to_labelstudio_sdk.py --check` 對帳通過後標一批，
   再 `--task pose` 清洗、排重訓單。
3. **在 5060 Ti 那台驗骨架疊圖端到端**：`DETECT_BROADCAST=1` 跑推論，
   前端切「偵測」看骨架有沒有對齊、切換模式影像會不會斷。
4. `device.stream_channel_detect` 欄位與 `GET /devices` 的 `stream_url_detect`
   **已無人拿來當播放網址**，但仍當成「這台鏡頭有接 AI」的判斷依據。
   要清乾淨得改資料表 + 補一個明確的 `has_ai` 欄位，不在本次範圍。

# agent/schemas.py
"""Agent 的資料契約（見 agent/docs/03-contracts.md）。

三類：
1. AlertMessage —— Kafka 1 進來的告警，驗證不過就進 DLQ。
2. ProcessedReport —— Kafka 2 出去的訊息，**必須是現有格式的超集**：
   舊欄位一個不動、一個不少，新欄位全部 optional，
   backend/kafka_consumer.py 不改也能跑（Never break userspace）。
   唯一的例外是 severity 與 yolo_threshold：後端已於 2026-07-19（commit 1bbb585）
   把這兩欄從 detect_events 與 EventCreateRequest 整組移除，現在送過去只會被
   Pydantic（預設 extra="ignore"）靜默丟掉。既然接收端已經沒有這兩欄，
   「不動舊欄位」就不再適用——本 Agent 亦同步不送。
3. 各節點的 structured output —— judge / al_curator 要 LLM 吐的形狀。
"""
from datetime import datetime
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator, model_validator

Verdict = Literal["true_alarm", "false_alarm", "uncertain"]

# 定時巡檢事件：走環境報告路徑，不做跌倒複判
ROUTINE_CHECK_EVENT = "Routine_Environment_Sanity_Check"


# ════════════════════════════════════════════════════════
# 1. Kafka 1 輸入
# ════════════════════════════════════════════════════════
class AlertMessage(BaseModel):
    """Kafka 1 進來的告警。

    **Kafka 1 上有兩種格式**（2026-07-20 核對邊緣端程式碼確認，非依文件範例）：

    1. 跌倒告警 —— `ai/inference_test.py` 的 `route_by_confidence()`
       `device_id`(int)、`event_type`、`yolo_threshold`、
       `clip_path`、`snapshot_path`… **沒有 camera_id 欄位**
       ⚠️ 2026-07-27：`event_type` 從此恆為 `"fall"`。原本還有 `"chair_slip"`（模組 I），
       該模組已隨 `ai/modules/` 白名單收斂刪除（見根目錄 `CLAUDE.md`）。欄位型別不變，
       仍是字串、不是 enum，所以本 schema 不需要改，只是值域少了一個。
    2. 定時巡檢 —— `ai/modules/sanity_check.py:35`
       `device_id`(int)、`camera_id`("Room_301_Bed" 這種非數字字串)、
       `event_type`("Routine_Environment_Sanity_Check")… **沒有 yolo_threshold**

    因此 device_id 的解析順序是：先讀 device_id（邊緣端已經算好且正確），
    沒有才退回從 camera_id 抽數字（沿用邊緣端自己的算法，Room_301_Bed → 301）。

    現況 `vlm_worker.py` 只讀 camera_id 且要求是數字，兩種格式都命不中，
    於是**每一筆慢車道事件都 fallback 成寫死的 device 101**，不論實際是哪台相機。
    正確的 device_id 明明就在訊息裡，只是沒人讀它。
    """

    event_type: str
    device_id: int                           # 正規化後的裝置編號
    camera_id: Optional[str] = None          # 邊緣端原始相機代號，保留供 log 與巡檢報告用
    image_filename: Optional[str] = None
    yolo_score: float = 0.0
    # 只走 Kafka 1（AI 內部），judge prompt 拿它跟 yolo_score 比大小用；不外發後端。
    yolo_threshold: float = 0.5              # 巡檢訊息不帶此欄位，用預設值
    detected_at: Optional[datetime] = None   # 可能缺，缺則由 publish 以收到時間補
    clip_path: Optional[str] = None          # 可能缺；注意這是整支來源影片，不是事件片段

    # ⚠️ 這兩欄非收不可，被 extra="ignore" 吃掉會出事（2026-08-04 cutover 前修）：
    #
    # snapshot_path —— 邊緣端 2026-07-31 起送的是 s3:// URI（inference_test.py:135）。
    #   後端 core/s3.py 的 parse_s3_uri() **只認 s3://**，不是就回 None、簽不出 presigned
    #   URL，前端事件詳情的快照就是空白。publish 原本改送 image_path（ImageStore 為了
    #   餵 VLM 而解析出的本機絕對路徑，見下方 AgentState），正好踩中這個坑。
    #   ai/vlm_worker.py:69-74 的註解就是在警告它，還註明「實測：走慢速道的事件全部中招」。
    #   仍是 Optional：巡檢訊息（ai/modules/sanity_check.py）不帶這欄，沒設 CLIP_S3_BUCKET
    #   的機器也不帶，那兩種情況要退回 image_path。
    #
    # person_label —— 多人同時跌倒時主迴圈每人各發一筆，兩筆的相機/時間/畫面完全一樣，
    #   靠這個「畫面內第 N 位倒地者」才分得出是兩個人還是系統重複報（inference_test.py:143）。
    #   它是 AI 內部欄位（護欄的 INTERNAL_ONLY_KEYS），**不外發後端**，只由 publish
    #   併進既有的 vlm_summary 字串，作法與 vlm_worker.py:83-85 相同。
    snapshot_path: Optional[str] = None
    person_label: Optional[str] = None

    model_config = {"extra": "ignore"}       # 邊緣端還會多送 severity/status 等，那些才是真的忽略即可

    @model_validator(mode="before")
    @classmethod
    def _resolve_device_id(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)

        if data.get("device_id") is not None:
            return data

        # 沒有 device_id 才退回 camera_id。抽數字的算法刻意與邊緣端一致
        # （inference_test.py:299 與 sanity_check.py:31 都是這樣算的），
        # 這樣 Agent 算出來的裝置編號跟邊緣端心裡想的是同一個。
        camera_id = data.get("camera_id")
        if camera_id is not None:
            digits = "".join(c for c in str(camera_id) if c.isdigit())
            if digits:
                data["device_id"] = int(digits)
        return data

    @field_validator("camera_id", mode="before")
    @classmethod
    def _stringify_camera_id(cls, v):
        # 邊緣端有時送 int 有時送 str，統一成 str
        return str(v) if v is not None else v

    @property
    def is_routine_check(self) -> bool:
        return self.event_type == ROUTINE_CHECK_EVENT

    @property
    def camera_label(self) -> str:
        """給人看的相機代號：優先用邊緣端原始字串，沒有就用裝置編號。"""
        return self.camera_id or str(self.device_id)


# ════════════════════════════════════════════════════════
# 2. Kafka 2 輸出（現有格式的超集）
# ════════════════════════════════════════════════════════
class ProcessedReport(BaseModel):
    """送往 processed-reports 的訊息。

    上半部欄位的名稱、型別、語意與 vlm_worker.py 現況完全一致；
    下半部是新增的 ai_* 欄位，全部 optional，舊 consumer 忽略也不壞。
    """

    # ── 既有欄位（不得更動）──
    # 註：severity 與 yolo_threshold 曾在此，已隨後端 2026-07-19 的清理一併移除，
    # 見本檔頂端說明。yolo_threshold 仍在 AlertMessage（Kafka 1）上，只是不外發。
    device_id: int
    event_type: str
    clip_path: str
    detected_at: str                      # ISO 8601 字串，對齊後端 datetime 解析
    snapshot_path: str
    yolo_score: float
    vlm_summary: str                      # VLM 原始報告

    # ── 新增欄位（全部 optional）──
    # None 代表「Agent 判不出來，交回人工」——等同現況，不是誤報建議
    ai_verdict: Optional[Literal["true_alarm", "false_alarm"]] = None
    ai_confidence: Optional[float] = None
    ai_reasoning: Optional[str] = None
    # 這裡刻意沒有通報單草稿欄位：已拍板改為前端開表單時即時產生（03-contracts.md §5）。
    # 草稿是一次 LLM 呼叫且只在 true_alarm 時需要，塞進這則訊息會讓跌倒通知等它產完。


# ════════════════════════════════════════════════════════
# 3. 節點 structured output
# ════════════════════════════════════════════════════════
class JudgeResult(BaseModel):
    """judge 節點要 LLM 吐的形狀（03-contracts.md §6）。

    解析失敗或重試耗盡 → 對外降級為 ai_verdict=null（交回人工），不丟例外中斷 consumer。
    """

    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    reasoning: str = Field(description="判定理由，繁體中文，寫給值班人員看")


class ALDecision(BaseModel):
    """al_curator 節點：這張圖值不值得收進回訓資料集（P4）。"""

    keep: bool
    reason: str
    priority: Literal["low", "medium", "high"] = "low"


# ════════════════════════════════════════════════════════
# 4. 流經整張圖的 State
# ════════════════════════════════════════════════════════
class AgentState(TypedDict, total=False):
    """LangGraph 的 state。用 total=False：節點只回傳自己負責的欄位，其餘由 LangGraph 合併。"""

    # 輸入
    raw: dict                    # Kafka 1 收到的原始訊息（ingest 之前唯一有值的欄位）
    alert: AlertMessage          # ingest 驗證後的告警
    # ingest 經 ImageStore 解析出的**本機絕對路徑**，只給 VLM 讀圖用。
    # ⚠️ 不要拿它當外發的 snapshot_path（後端只認 s3://），理由見 AlertMessage.snapshot_path。
    image_path: str
    # 同一事件的連續畫面（時序判讀用）。有值時 vlm_analyze 會一次全部餵給 VLM，
    # 單張畫面分不出「躺著休息」與「跌倒」，姿態的變化才是關鍵
    image_paths: Optional[list[str]]

    # 中間產物
    vlm_report: Optional[str]
    vlm_retries: int
    judge_retries: int
    judge_max_retries: int       # 組圖時綁入，讓分支純函式不必去讀全域設定
    followup: Optional[str]      # judge 判 uncertain 時，回頭要 VLM 補答的問題

    # 產出
    verdict: Verdict
    confidence: float
    reasoning: str
    al_decision: Optional[ALDecision]

    # 流程控制：ingest 擋掉的壞資料在這裡標記原因，後續節點直接短路
    error: Optional[str]

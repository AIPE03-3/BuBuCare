# agent/prompts.py
"""所有 prompt 集中在這裡，節點只負責流程不負責措辭。

- 複判用的 VLM prompt 已於 2026-07-20 改寫為中性描述（原因見下方註解）。
- 巡檢用的 VLM prompt 仍沿用 vlm_worker 現況：巡檢本來就是要一份報告，
  不是要它做真假判定，誘導性的問題在那條路徑上不存在。
- judge 的 prompt 是新的：它要的不是報告，是可機讀的判定。
"""
from agent.schemas import AlertMessage

# ── VLM：跌倒/滑落二審 ──────────────────────────────────
#
# 2026-07-20 改寫。原本沿用 vlm_worker 的「緊急通報單」模板，但實測證明那是誘導性提問：
# 先告訴模型「邊緣端偵測到 Fall_Detected」再要它填寫【緊急通報】表格（含「狀況確認」
# 「現場風險評級」「醫療建議行動」），模型就會順著前提確認跌倒。
# 實例：一名女性站立行走的畫面，舊 prompt 讓 VLM 產出「後腦勺靠近牆壁，可能有跌倒風險、
# 風險評級：高」，完全沒描述畫面實況。二審的意義是獨立查證，不是幫邊緣端背書。
#
# 新版只問「看得見什麼」，不提警報、不給邊緣端分數、不要它下結論——判定是 judge 的工作。
# 實測同一批圖，改用中性描述後：誤報不再被確認成真警報，真跌倒的信心從 0.80 升到 0.90–0.95。
VLM_REVIEW_TEMPLATE = (
    "You must reply ONLY in Traditional Chinese (繁體中文).\n"
    "你是安養中心的監視畫面觀察員。請客觀描述畫面裡你**實際看得見**的內容。\n"
    "不要推測、不要下結論、不要提到任何警報或風險評級。\n\n"
    "請用以下格式回答：\n\n"
    "【現場畫面描述】\n"
    "1. 人數: （看不到人就直接說沒有看到人）\n"
    "2. 身體姿態: （站立／行走／坐著／跪著／躺臥／趴伏）\n"
    "3. 與地面的關係: （站在地上／坐在椅子或床上／身體貼著地面）\n"
    "4. 周圍物品: （有無翻倒的物品或散落物）\n"
    "5. 畫面品質: （清晰／模糊／過曝／過暗／被遮蔽；看不清楚就明說）"
)

# 多張連續畫面時追加這段：時序資訊才分得出「躺著休息」與「跌倒」
VLM_SEQUENCE_PREFIX = (
    "以下是同一台攝影機的 {count} 張連續畫面，依時間先後排列。\n"
    "請先逐張描述，再說明**姿態如何隨時間變化**（例如：站立→倒地、全程坐著沒動）。\n\n"
)

# ── VLM：定時環境巡檢（沿用 vlm_worker 現況模板）─────────────
VLM_ROUTINE_TEMPLATE = (
    "You must reply ONLY in Traditional Chinese (繁體中文).\n"
    "You are an AI head nurse conducting a routine security check. "
    "Inspect if there are any potential environmental hazards.\n"
    "Please output a structured environment report using this exact template:\n\n"
    "【安養中心智慧環境巡檢報告】\n"
    "1. 巡檢相機: {camera_id}\n"
    "2. 巡檢狀態: 正常 / 發現潛在隱患\n"
    "3. 現場環境具體描述: \n"
    "4. 預防性護理建議: "
)

# judge 判不出來時，帶著具體問題回頭再問 VLM 一次。
# 只問「看得見什麼」，不問「這是不是跌倒」——判定是 judge 的工作，不是 VLM 的
VLM_FOLLOWUP_SUFFIX = (
    "\n\n【補充追問】前一次判讀資訊不足以下結論。請特別描述以下幾點，只描述你實際看得見的："
    "\n- 畫面中人物的身體姿態（站立／坐姿／躺臥／倒臥），以及身體與地面的接觸情況"
    "\n- 人物所在位置（床上／床邊地面／走道／椅子）"
    "\n- 是否有翻倒的物品、散落物或其他異常"
    "\n- 若畫面模糊、遮蔽或根本看不到人，請直接說明看不到，不要臆測。"
)


def build_vlm_review_prompt(
    alert: AlertMessage, followup: str | None = None, image_count: int = 1
) -> str:
    """組視覺判讀 prompt。

    刻意不帶入 alert 的 event_type 與 yolo_score：那是誘導資訊，會讓模型順著前提回答。
    alert 參數保留是為了讓呼叫端介面一致，以及未來若有非誘導性的欄位可用。
    """
    prompt = VLM_REVIEW_TEMPLATE
    if image_count > 1:
        prompt = VLM_SEQUENCE_PREFIX.format(count=image_count) + prompt
    if followup:
        prompt += followup
    return prompt


def build_vlm_routine_prompt(alert: AlertMessage) -> str:
    return VLM_ROUTINE_TEMPLATE.format(camera_id=alert.camera_label)


# ── judge：綜合判定 ──────────────────────────────────────
JUDGE_TEMPLATE = """你是安養中心的 AI 複判護理長，負責覆核邊緣端 AI 送來的跌倒告警。

【本次告警】
- 事件類型：{event_type}
- 相機編號：{camera_id}
- 邊緣端 YOLO 信心度：{yolo_score:.2f}，{score_vs_threshold}

【VLM 影像判讀報告】
{vlm_report}

【判定規則】
1. verdict 三選一：
   - true_alarm：影像證據支持確實發生跌倒或需要立即介入的狀況
   - false_alarm：影像證據明確顯示是誤判（例如人正常坐臥、畫面中根本沒有人、是物品掉落）
   - uncertain：影像模糊、遮蔽、資訊不足，無法判斷
2. 安全優先：這是照護場景，漏報一次跌倒的代價是人命。**只要有合理可能是真的跌倒，就判 true_alarm。**
   證據不足時判 uncertain，**絕對不要為了給答案而判 false_alarm**。
3. confidence 是你對自己這個判定的信心（0~1），不是 YOLO 的分數。
4. reasoning 用繁體中文寫給值班護理人員看，講清楚你依據影像中的什麼證據做此判定，兩三句話即可。
"""


AL_CURATOR_TEMPLATE = """你是機器學習資料集的策展人，負責挑出「值得拿來重新訓練跌倒偵測模型」的樣本。

【這起事件】
- 事件類型：{event_type}
- 邊緣端 YOLO 信心度：{yolo_score:.2f}（觸發門檻 {yolo_threshold:.2f}）
- VLM 影像判讀：{vlm_report}
- 複判結果：{verdict}（信心 {confidence:.2f}）
- 判定理由：{reasoning}

【什麼樣本值得收】
高價值的是**邊緣端模型判錯或判得勉強**的樣本，因為那才是它的盲點：
1. YOLO 分數低（勉強過門檻甚至沒把握），但複判確認是真跌倒 → 漏抓的盲點，最有價值
2. YOLO 分數高，但複判確認是誤報 → 誤觸發的盲點，同樣有價值
3. YOLO 分數落在模糊地帶，複判也難以確定 → 邊界樣本，中等價值

【什麼不值得收】
- YOLO 判得又準又有把握，複判也完全同意 → 模型已經會了，收了是浪費
- 影像本身無法判讀（全黑、嚴重遮蔽）→ 訓練用不上

【輸出】
- keep：是否收錄
- reason：繁體中文，一句話說明為什麼收或不收，要具體指出是哪一類盲點
- priority：high=明確的模型盲點；medium=邊界樣本；low=參考價值有限
"""


def build_al_curator_prompt(alert: AlertMessage, state: dict) -> str:
    return AL_CURATOR_TEMPLATE.format(
        event_type=alert.event_type,
        yolo_score=alert.yolo_score,
        yolo_threshold=alert.yolo_threshold,
        vlm_report=state.get("vlm_report") or "（未取得影像判讀）",
        verdict=state.get("verdict", "uncertain"),
        confidence=state.get("confidence", 0.0),
        reasoning=state.get("reasoning", ""),
    )


def describe_score_vs_threshold(score: float, threshold: float) -> str:
    """把「分數 vs 門檻」的比較先算好再寫進 prompt。

    7B 等級的地端模型比大小會出錯——實測它把 0.58 說成「略低於門檻值 0.50」，
    然後據此推論「資訊不足」。數字比較是程式的強項、模型的弱項，不要交給模型做。
    """
    if score > threshold:
        return f"高於觸發門檻 {threshold:.2f}"
    if score < threshold:
        return f"低於觸發門檻 {threshold:.2f}"
    return f"剛好等於觸發門檻 {threshold:.2f}"


def build_judge_prompt(alert: AlertMessage, vlm_report: str) -> str:
    return JUDGE_TEMPLATE.format(
        event_type=alert.event_type,
        camera_id=alert.camera_label,
        yolo_score=alert.yolo_score,
        score_vs_threshold=describe_score_vs_threshold(alert.yolo_score, alert.yolo_threshold),
        vlm_report=vlm_report,
    )

"""LangGraph Uncertainty Router —— 第 2 層決策層,插在 inference_test(產事件) 與
processed-reports(後端落庫) 之間,接管「何時找 VLM 二審、帶什麼 prompt、灰區怎麼分流」。

為什麼是這一層(而不是整支移植 Albert 的 StateGraph):
  - Albert(origin/albert_chiang:Fall/tools/vlm_worker.py)的 StateGraph 外發 payload 多了
    fall_reason_item/item_description、少了 severity/yolo_threshold,且在 worker 端重新
    RTDETR(...) 本地跑一次偵測當分流依據。本機三顆模型都上 Triton、AcT 信心在 inference_test
    端已算好隨事件帶出,且後端 EventCreateRequest(backend/events/router.py) 沒有那兩個欄位
    (Pydantic 預設 ignore 會靜默丟掉)。故取其形(StateGraph 節點化 + conditional router)、
    不取其實(payload/模型)。

紅線(硬約束):吃的事件 topic(nursing-home-alerts)、吐的 processed-reports payload 欄位
(device_id/event_type/clip_path/detected_at/snapshot_path/yolo_score/yolo_threshold/
vlm_summary/severity)一個都不動 —— 後端完全感覺不到本層存在。本 Router 只回填
vlm_summary/severity/should_send;最終 payload 的「組裝與外發」留在 vlm_worker 主迴圈。

兩個定案:
  - 一律二審:巡檢/其餘全走 vlm_review,不加 discard 出口(長照寧可誤審不漏報);
    唯一不外發出口 = 找不到快照圖。
  - 方案 B:VLM 若判出跌倒關鍵物,解析 fall_reason_item/item_description 存進 RouterState
    給主動學習打包當標註線索(見 package_active_learning_sample),但絕不進外發 payload。
"""
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from typing_extensions import TypedDict

from langgraph.graph import END, StateGraph

from vlm_client import VLMModel  # VLM 推論介面(後端目前 Ollama,之後可換 Triton),介面不變

# 警報快照由 inference_test.py 寫入 ai/snapshots/(以 __file__ 為基準)。Router 讀圖的 base_dir
# 必須對齊那個位置,否則靠 image_filename 拼路徑會找不到圖。與 vlm_worker 的常數保持一致。
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"
# 主動學習資料集也以本檔為基準,落在 ai/ 下,和 snapshots 一致(不受啟動目錄影響)。
DATASET_DIR = Path(__file__).resolve().parent / "active_learning_dataset"

# VLM 推論介面。觸發/路由邏輯歸本 Router,推論後端隔離在 VLMModel 內(換 Triton 只改 vlm_client)。
vlm_model = VLMModel()


# =========================================================================
# 📝 Router 狀態(只放流程用中間狀態,不放後端契約以外的東西進最終 payload)
# =========================================================================
class RouterState(TypedDict, total=False):
    event_data: Dict[str, Any]   # 原始 Kafka 事件(payload 由 worker 主迴圈用它組,不在此改)
    img_path: str                # 解析出的快照絕對路徑
    alert_type: str              # event_type 字串(fall / chair_slip / Routine_Environment_Sanity_Check ...)
    cam_id: str                  # 顯示用房號(Device_{device_id})
    env_clues: str               # 邊緣端環境線索(餵進 prompt)
    yolo_score: float            # 事件帶進來的信心(不重算,不本地載模型)
    route: str                   # 分流結果:vlm_review(目前唯一二審出口)
    vlm_summary: str             # VLM 判讀文字 → 回填外發 payload 的 vlm_summary
    severity: str                # low/medium/high → 回填外發 payload 的 severity
    should_send: bool            # False = 不外發(唯一出口:找不到圖)
    # 方案 B:VLM 判出的跌倒關鍵物,只留在狀態內給主動學習用,不進外發 payload。
    fall_reason_item: str
    item_description: str


# =========================================================================
# 🧠 主動學習打包引擎(沿用 vlm_worker 現行行為,額外吃 VLM 關鍵物標籤)
# =========================================================================
def package_active_learning_sample(img_path, camera_id, alert_type, yolo_score,
                                   vlm_inferred_label: Optional[str] = None):
    """VLM 二審時,若樣本落在 YOLO 弱點視窗,打包相片 + 粗略 YOLO-Pose 標註做主動學習教材。

    方案 B:若 VLM 判出跌倒關鍵物(vlm_inferred_label),把它記進標註旁註,給後續 Label Studio
    標註當線索([[dgroup-training-loop]] 需要「哪個物件害的」)。仍不外發到 processed-reports。
    """
    try:
        dataset_base = str(DATASET_DIR)
        os.makedirs(f"{dataset_base}/images", exist_ok=True)
        os.makedirs(f"{dataset_base}/labels", exist_ok=True)

        base_name = os.path.basename(img_path)
        label_name = base_name.replace(".jpg", ".txt")

        import shutil
        shutil.copy(img_path, f"{dataset_base}/images/{base_name}")

        with open(f"{dataset_base}/labels/{label_name}", "w") as f:
            # 虛擬標註格式: <class_id=0 (person)> <cx> <cy> <w> <h> [17個關鍵點x,y]
            mock_pose_annotation = "0 0.500 0.600 0.300 0.500" + " 0.500 0.550 2.0" * 17
            f.write(mock_pose_annotation + "\n")
            # 方案 B:VLM 判出的關鍵物寫成註解行,不影響 YOLO-Pose 標註格式,供標註參考。
            if vlm_inferred_label and vlm_inferred_label != "unknown":
                f.write(f"# vlm_fall_reason_item: {vlm_inferred_label}\n")

        tag = f"（關鍵物: {vlm_inferred_label}）" if vlm_inferred_label and vlm_inferred_label != "unknown" else ""
        print(f"💾 [Active Learning] 成功攔截 YOLO 弱點！照片與自動標註已打包：{base_name} "
              f"(YOLO置信度: {yolo_score:.2f}){tag}")
    except Exception as e:
        print(f"⚠️ [Active Learning] 自動標註打包失敗: {e}")


# =========================================================================
# 🕸️ LangGraph 節點
# =========================================================================
def preprocess_node(state: RouterState) -> Dict[str, Any]:
    """前處理:解析事件、算 img_path、設 alert_type/cam_id/env_clues/yolo_score。找不到圖 → 不外發。"""
    event_data = state["event_data"]

    alert_type = event_data.get("event_type", "Pending_VLM_Review")
    # 契約欄位是 device_id(int)(inference 端從沒送 camera_id)。用 device_id 當房號來源。
    device_id = event_data.get("device_id", 0)
    cam_id = f"Device_{device_id}"
    env_clues = event_data.get("event_type", "No specific objects")

    try:
        yolo_score = float(event_data.get("yolo_score", 0.0))
    except (TypeError, ValueError):
        yolo_score = 0.0

    image_filename = event_data.get("image_filename")
    base_dir = str(SNAPSHOT_DIR)  # 對齊 inference_test.py 寫快照的 ai/snapshots/
    if image_filename:
        img_path = os.path.join(base_dir, image_filename)
    else:
        img_path = os.path.join(base_dir, f"snapshot_{device_id}.jpg")

    # 找不到圖:短暫等一下(快照與事件可能有寫入時序差),仍找不到就不外發。
    if not os.path.exists(img_path):
        time.sleep(1.0)
        if not os.path.exists(img_path):
            print(f"⚠️ [警告] 找不到房間 {cam_id} 的實體照片：{img_path}，將跳過此筆視覺審查。")
            return {"should_send": False}

    return {
        "img_path": img_path,
        "alert_type": alert_type,
        "cam_id": cam_id,
        "env_clues": env_clues,
        "yolo_score": yolo_score,
        "should_send": True,
    }


def route_decision(state: RouterState) -> str:
    """Uncertainty Router 核心:決定分流方向。

    定案:一律二審,不加 discard。進到本 worker 的事件全是低信心/遮擋待審(高信心事件在
    inference_test 端就走 processed-reports 快速道、不進 nursing-home-alerts),故一律 vlm_review。
    唯一的不外發出口 = preprocess 找不到圖(should_send=False)。
    """
    if not state.get("should_send", True):
        return END
    # 巡檢與其餘都走 vlm_review(prompt 在節點內依 alert_type 分 A/B)。
    return "vlm_review"


def vlm_review_node(state: RouterState) -> Dict[str, Any]:
    """VLM 二審:依 alert_type 組 prompt A/B、呼叫 VLM、觸發主動學習、回填 vlm_summary/severity。"""
    alert_type = state["alert_type"]
    cam_id = state["cam_id"]
    env_clues = state["env_clues"]
    img_path = state["img_path"]
    yolo_score = state["yolo_score"]
    confidence = f"{yolo_score * 100:.1f}%" if yolo_score > 0 else "0.0%"

    # ── Prompt 分流(沿用 vlm_worker 現行兩段 prompt,一字不改)──
    if alert_type == "Routine_Environment_Sanity_Check":
        print(f"\n[🔍 定時巡檢] 房間：{cam_id}。讀取專屬歷史照片：{os.path.basename(img_path)}")
        prompt_text = (
            "You must reply ONLY in Traditional Chinese (繁體中文).\n"
            "You are an AI head nurse conducting a routine security check. "
            "Inspect if there are any potential environmental hazards.\n"
            "Please output a structured environment report using this exact template:\n\n"
            "【安養中心智慧環境巡檢報告】\n"
            f"1. 巡檢相機: {cam_id}\n"
            "2. 巡檢狀態: 正常 / 發現潛在隱患\n"
            "3. 現場環境具體描述: \n"
            "4. 預防性護理建議: "
        )
    else:
        print(f"\n[🔔 疑似跌倒/滑落二審] 房間：{cam_id}。讀取專屬證據照片：{os.path.basename(img_path)}")
        prompt_text = (
            "You must reply ONLY in Traditional Chinese (繁體中文).\n"
            "You are an AI head nurse in a security care center. Look at this security snapshot carefully.\n"
            f"The edge system detected these objects nearby: {env_clues}.\n"
            "Analyze the image and output a structured alert report using this exact template:\n\n"
            "【安養中心緊急通報（多模態二審版）】\n"
            f"1. 通報相機: {cam_id}\n"
            "2. 狀況確認: \n"
            "3. 現場風險評級: \n"
            f"4. AI 判讀信心度: (邊緣置信度為 {confidence}，請重新評估)\n"
            "5. 醫療建議行動: \n\n"
            # 方案 B:額外請 VLM 在尾端吐一組關鍵物 JSON(只給主動學習用,不外發)。
            "==============================\n"
            "【主動探索學習模組】\n"
            "請在報告最尾端，嚴格且只以一組完整的 JSON 格式（不要包含 markdown 標籤或 ```json 字樣）"
            "輸出你看到畫面中「最可能導致跌倒/異常的物品或現場關鍵物（例如 slipper, wire, iv_pole, "
            "walker，如無危險物請輸出 'unknown'）」，格式必須完全對齊如下：\n"
            '{"item_name": "物品英文名", "description": "物品的中文具體描述與現場狀況分析"}'
        )

    fall_reason_item = "unknown"
    item_description = "無偵測到特定危險雜物"

    try:
        start_time = time.time()
        raw_report = vlm_model.infer(prompt_text, img_path)
        print(f"✨ [{cam_id}] VLM 處理完畢，耗時 {time.time() - start_time:.2f} 秒。")

        # 方案 B:解析尾端關鍵物 JSON,抽出後從報告本體移除(不讓 JSON 髒了 vlm_summary)。
        if alert_type != "Routine_Environment_Sanity_Check":
            try:
                json_match = re.search(r'\{\s*"item_name".*?\}', raw_report, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    extracted = json.loads(json_str)
                    fall_reason_item = extracted.get("item_name", "unknown")
                    item_description = extracted.get("description", "無偵測到特定危險雜物")
                    raw_report = (raw_report.replace(json_str, "")
                                  .replace("==============================", "")
                                  .replace("【主動探索學習模組】", "").strip())
            except Exception as je:
                print(f"⚠️ 解析 VLM 關鍵物 JSON 失敗（不影響外發）: {je}")

        # MLOps 主動學習:YOLO 弱點視窗(0.35~0.85)才打包,把 VLM 判出的關鍵物一併帶進去。
        if alert_type != "Routine_Environment_Sanity_Check" and (0.35 <= yolo_score <= 0.85):
            active_label = fall_reason_item if fall_reason_item != "unknown" else None
            package_active_learning_sample(img_path, cam_id, alert_type, yolo_score,
                                           vlm_inferred_label=active_label)

    except Exception as e:
        print(f"❌ VLM 推理失敗: {str(e)}")
        raw_report = f"【系統警告】二審推理中斷。房間: {cam_id}，原因: {str(e)}"

    # severity 對齊後端契約語意:event_type 實際是小寫 "fall"/"chair_slip"。
    severity = "high" if str(alert_type).lower() in ("fall", "chair_slip") else "low"

    return {
        "vlm_summary": raw_report,
        "severity": severity,
        "fall_reason_item": fall_reason_item,   # 方案 B:留狀態,不外發
        "item_description": item_description,    # 方案 B:留狀態,不外發
    }


# =========================================================================
# 🛠️ 構建並編譯 StateGraph
# =========================================================================
def build_router():
    workflow = StateGraph(RouterState)
    workflow.add_node("preprocess", preprocess_node)
    workflow.add_node("vlm_review", vlm_review_node)
    workflow.set_entry_point("preprocess")
    workflow.add_conditional_edges(
        "preprocess",
        route_decision,
        {"vlm_review": "vlm_review", END: END},
    )
    workflow.add_edge("vlm_review", END)
    return workflow.compile()


# 模組載入即編譯,供 vlm_worker import 使用:router_app.invoke({"event_data": event})。
router_app = build_router()
print("✅ [Uncertainty Router] LangGraph 狀態圖編譯成功！(一律二審 + 方案 B 關鍵物留狀態)")

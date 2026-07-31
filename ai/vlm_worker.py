import json
import time
from kafka import KafkaConsumer, KafkaProducer

# 第 2 層 LangGraph Uncertainty Router:接管「何時找 VLM 二審、帶什麼 prompt、灰區怎麼分流」。
# worker 只負責 Kafka 收/發 + 最終 payload 組裝(契約邊界),中間的決策全交給 router。
# prompt 分流、VLM 呼叫、主動學習打包、關鍵物解析都在 uncertainty_router 內(見該檔說明)。
from uncertainty_router import router_app

print("📦 [VLM 業界生產級多路核心啟動] 正在連線地端 Kafka 流數據引擎...")

# 1. 監聽前段 Kafka 1 (Topic: nursing-home-alerts)
consumer = KafkaConsumer(
    'nursing-home-alerts',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda v: json.loads(v.decode('utf-8')),
    auto_offset_reset='latest',
    group_id='vlm-brain-cluster'
)

# 2. 準備轉發到後段 Kafka 2 (Topic: processed-reports)
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

print("🚀 [護理長 LangGraph Agent 上線] 監聽中... Uncertainty Router 已接管二審決策！")


# =========================================================================
# 📥 主數據流監聽循環
# =========================================================================
# 決策(prompt 分流 / VLM 呼叫 / 主動學習 / 關鍵物解析)交給 Router;worker 這裡只做
# 「拿事件 → 丟進 Router → 用 Router 回填的 vlm_summary 組最終契約 payload → 外發」。
for message in consumer:
    event_data = message.value

    # 🧠 Router 接管:回填 vlm_summary / should_send（找不到圖時 should_send=False）。
    result = router_app.invoke({"event_data": event_data})

    if not result.get("should_send", False):
        # 唯一不外發出口:preprocess 找不到快照圖(已在 Router 內印過警告)。
        continue

    # =========================================================================
    # 📢 外發 Kafka 2 管道（完全對齊後端 EventCreateRequest 規格）——契約邊界,欄位不動。
    # 事件帶進來的 yolo_threshold 是 AI 內部欄位(給二審端比對信心用),刻意不放進外發 payload;
    # severity 則已隨後端 2026-07-19 的清理(commit 1bbb585)移除,後端不再有該欄位。
    # =========================================================================
    # device_id 是契約欄位(int),直接沿用事件帶進來的值。
    try:
        clean_device_id = int(event_data.get("device_id", 0))
    except (TypeError, ValueError):
        clean_device_id = 101

    try:
        clean_yolo_score = float(event_data.get("yolo_score", 0.0))
    except (TypeError, ValueError):
        clean_yolo_score = 0.0

    # 生成 ISO 8601 標準時間字串,對齊後端 datetime(事件帶了就沿用)。
    iso_detected_at = event_data.get("detected_at", time.strftime("%Y-%m-%dT%H:%M:%S"))

    final_report = {
        "device_id": clean_device_id,                                   # room_no -> device_id (int)
        "event_type": result["alert_type"],                             # 對齊 event_type 字串
        "clip_path": event_data.get("clip_path", "/vids/fallback.mp4"), # 後端必填影片路徑
        "detected_at": iso_detected_at,                                 # timestamp -> detected_at (ISO)
        # ⚠️ 沿用主迴圈原本帶的 snapshot_path（2026-07-31 起是 s3:// URI），**不要**改成
        # result["img_path"]。那是 Router 為了讀圖餵 VLM 而重組的**本機絕對路徑**，
        # 寫進後端會讓 core/s3.py 簽不出 presigned URL（它只認 s3://），
        # 前端的事件快照就永遠是空的。實測：走慢速道的事件全部中招。
        # 主迴圈沒帶時才退回本機路徑（沒設 CLIP_S3_BUCKET 的機器，行為與改動前相同）。
        "snapshot_path": event_data.get("snapshot_path") or result["img_path"],
        "yolo_score": clean_yolo_score,                                 # confidence(字串) -> yolo_score (float)
        "vlm_summary": result["vlm_summary"],                           # Router 回填的 VLM 判讀文字
    }
    # 多人同時跌倒：主迴圈會為每個倒地的人各發一筆事件，兩筆在事件中心的相機、時間、
    # 畫面全都一樣，護理師分不出是兩個人還是系統重複報。主迴圈把「第 N 位」放在
    # person_label（AI 內部欄位，不外發後端），這裡把它接到 VLM 判讀文字前面 ——
    # 否則上面那行會把主迴圈原本寫在 vlm_summary 裡的「第 N 位」整段覆蓋掉。
    # 後端欄位一個字沒加：person_label 本身不外發，只是併進既有的 vlm_summary 字串。
    _person_label = event_data.get("person_label") or ""
    if _person_label:
        final_report["vlm_summary"] = f"【{_person_label}】{final_report['vlm_summary']}"
    # 注意:Router 內部另有 fall_reason_item/item_description(方案 B,給主動學習用),
    # 刻意不放進 final_report —— 後端 EventCreateRequest 無此欄位,守住後端零感知。

    producer.send('processed-reports', value=final_report)
    producer.flush()
    print(f"📢 [Kafka 2] 雙軌審查報告已外發！已完成 EventCreateRequest 工業級規格轉換！")

import json
import time
import os
import ollama  
from kafka import KafkaConsumer, KafkaProducer

print("📦 [VLM 業界生產級多路核心啟動] 正在連線地端 Kafka 流數據引擎...")

# 1. 監聽前段 Kafka 1 (Topic: nursing-home-alerts)
consumer = KafkaConsumer(
    'nursing-home-alerts',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda v: json.loads(v.decode('utf-8')), 
    auto_offset_reset='latest',  # 👈 核心修改：直接跳過堆積的舊格式訊息，只聽重啟後的最新訊息！
    group_id='vlm-brain-cluster'
)

# 2. 準備轉發到後段 Kafka 2 (Topic: processed-reports)
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

print("🚀 [護理長大腦上線] 監聽中... 已解鎖多路不覆寫相片、最新流數據實時留存機制！")

for message in consumer:
    event_data = message.value
    
    # =========================================================================
    # 🎯 核心修改：精準對齊邊緣端 (inference_test.py) 丟過來的欄位名稱
    # =========================================================================
    alert_type = event_data.get("event_type", "Pending_VLM_Review") # 對齊 event_type
    cam_id = event_data.get("camera_id", "Unknown_Room")           # 物理對齊！camera_id -> cam_id
    env_clues = event_data.get("event_type", "No specific objects") # 將事件型態作為環境線索
    
    # 將邊緣端發出的 float 分數 (如 0.75) 轉換為 Prompt 內使用的百分比字串 (如 75.0%)
    yolo_score = event_data.get("yolo_score", 0.0)
    confidence = f"{yolo_score * 100:.1f}%" if yolo_score > 0 else "0.0%"
    
    # 自動生成一個帶有房間與時間戳的唯一告警 ID
    alert_id = f"ALT_{cam_id}_{time.strftime('%Y%m%d_%H%M%S')}"
    
    # 🎯 讀取 YOLO 這次端點傳過來的專屬不重複相片名稱
    image_filename = event_data.get("image_filename")
    
    base_dir = "/Users/albert/Documents/專案/AIPE03/Fall"
    
    if image_filename:
        # 直接精準配對 YOLO 存下來的那張帶有時間戳記的照片
        img_path = os.path.join(base_dir, image_filename)
    else:
        # 備援：若沒傳 image_filename，則嘗試尋找傳統格式相片
        img_path = os.path.join(base_dir, f"snapshot_{cam_id}.jpg")
    
    # 實體檔案就緒檢查
    if not os.path.exists(img_path):
        time.sleep(1.0)  # 給硬碟寫入一秒鐘的黃金緩衝時間
        if not os.path.exists(img_path):
            print(f"⚠️ [警告] 找不到房間 {cam_id} 的實體照片：{img_path}，將跳過此筆視覺審查。")
            continue

    # =========================================================================
    # 🚦 Prompt 分流切換
    # =========================================================================
    if alert_type == "Routine_Environment_Sanity_Check":
        print(f"\n[🔍 定時巡檢] 房間：{cam_id}。讀取專屬歷史照片：{image_filename}")
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
        resolved_alert_type = "Sanity_Check_Resolved"
    else:
        print(f"\n[🔔 疑似跌倒/滑落二審] 房間：{cam_id}。讀取專屬證據照片：{image_filename}")
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
            "5. 醫療建議行動: "
        )
        resolved_alert_type = "Fall_With_VLM_Resolved"

    raw_report = None

    try:
        start_time = time.time()
        # 🧠 呼叫官方 SDK 傳入精準新相片
        response = ollama.chat(
            model='llava:latest',
            messages=[{
                'role': 'user',
                'content': prompt_text,
                'images': [img_path]  
            }]
        )
        raw_report = response['message']['content'].strip()
        print(f"✨ [{cam_id}] VLM 處理完畢，耗時 {time.time() - start_time:.2f} 秒。")
            
    except Exception as e:
        print(f"❌ Ollama 推理失敗: {str(e)}")
        raw_report = f"【系統警告】二審推理中斷。房間: {cam_id}，原因: {str(e)}"

    # =========================================================================
    # 📢 外發 Kafka 2 管道 (同樣把新相片路徑傳給前端，讓網頁能顯示正確歷史照片)
    # =========================================================================
    if raw_report is not None:
        final_report = {
            "alert_id": alert_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            "room_no": cam_id,
            "env_clues": env_clues,
            "confidence": confidence,
            "alert_type": resolved_alert_type,
            "vlm_summary": raw_report,  
            "vlm_report": raw_report,
            "saved_image_path": img_path,  
            "status": "UNREAD"
        }
        
        producer.send('processed-reports', value=final_report)
        producer.flush()
        print(f"📢 [Kafka 2] 雙軌審查報告已外發！歷史證據照片已留存：{image_filename}")
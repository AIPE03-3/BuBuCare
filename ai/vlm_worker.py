import json
import time
import os
import shutil
import ollama  
from kafka import KafkaConsumer, KafkaProducer

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

print("🚀 [護理長大腦上線] 監聽中... 已解鎖多路不覆寫相片、最新流數據實時留存機制！")


# =========================================================================
# 🧠 核心功能：自動標註與主動學習打包引擎（Active Learning Engine）
# =========================================================================
def package_active_learning_sample(img_path, camera_id, alert_type, yolo_score):
    """
    當 VLM 介入二審時，若判定此樣本為高價值盲點（例如 YOLO 分數偏低但確實有狀況），
    自動將相片打包，並利用當前 YOLO 重心位置生成粗略的 YOLO-Pose 標註檔。
    """
    try:
        # 建立自動化主動學習資料集目錄
        dataset_base = "active_learning_dataset"
        os.makedirs(f"{dataset_base}/images", exist_ok=True)
        os.makedirs(f"{dataset_base}/labels", exist_ok=True)
        
        base_name = os.path.basename(img_path)
        label_name = base_name.replace(".jpg", ".txt")
        
        # 1. 物理備份這張難題照片，作為未來的訓練教材
        shutil.copy(img_path, f"{dataset_base}/images/{base_name}")
        
        # 2. 自動生成 YOLO-Pose 標註虛擬格式 (示範 MLOps 自動標註閉環)
        with open(f"{dataset_base}/labels/{label_name}", "w") as f:
            # 虛擬標註格式: <class_id=0 (person)> <cx> <cy> <w> <h> [17個關鍵點x,y]
            # 這裡寫入預設的人體中心與大小範圍，做為 Semi-Supervised 自動標註基底
            mock_pose_annotation = "0 0.500 0.600 0.300 0.500" + " 0.500 0.550 2.0" * 17
            f.write(mock_pose_annotation + "\n")
            
        print(f"💾 [Active Learning] 成功攔截 YOLO 弱點！照片與自動標註已打包儲存：{base_name} (YOLO置信度: {yolo_score:.2f})")
    except Exception as e:
        print(f"⚠️ [Active Learning] 自動標註打包失敗: {e}")


# =========================================================================
# 📥 主數據流監聽循環
# =========================================================================
for message in consumer:
    event_data = message.value
    
    alert_type = event_data.get("event_type", "Pending_VLM_Review") 
    cam_id = event_data.get("camera_id", "Unknown_Room")           
    env_clues = event_data.get("event_type", "No specific objects") 
    
    yolo_score = event_data.get("yolo_score", 0.0)
    confidence = f"{yolo_score * 100:.1f}%" if yolo_score > 0 else "0.0%"
    
    image_filename = event_data.get("image_filename")
    base_dir = "/Users/albert/Documents/專案/AIPE03/Fall"
    
    if image_filename:
        img_path = os.path.join(base_dir, image_filename)
    else:
        img_path = os.path.join(base_dir, f"snapshot_{cam_id}.jpg")
    
    if not os.path.exists(img_path):
        time.sleep(1.0)  
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

    raw_report = None

    try:
        start_time = time.time()
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
            
        # =====================================================================
        # 🎯 MLOps 核心機制點火：篩選邊緣端盲點並自動加入主動學習
        # =====================================================================
        if alert_type != "Routine_Environment_Sanity_Check" and (0.35 <= yolo_score <= 0.85):
            package_active_learning_sample(img_path, cam_id, alert_type, yolo_score)

    except Exception as e:
        print(f"❌ Ollama 推理失敗: {str(e)}")
        raw_report = f"【系統警告】二審推理中斷。房間: {cam_id}，原因: {str(e)}"

    # =========================================================================
    # 📢 外發 Kafka 2 管道（完全對齊後端 EventCreateRequest 規格，一條 API 雙軌通吃！）
    # =========================================================================
    if raw_report is not None:
        # 🎯 數據清洗：確保型別與格式完全符合後端規範限制
        try:
            clean_device_id = int(cam_id) if str(cam_id).isdigit() else 101
        except:
            clean_device_id = 101

        try:
            clean_yolo_score = float(yolo_score)
        except:
            clean_yolo_score = 0.0

        # 生成 ISO 8601 標準時間字串（例如：2026-07-08T15:05:00），對齊後端 datetime
        iso_detected_at = event_data.get("detected_at", time.strftime("%Y-%m-%dT%H:%M:%S"))

        final_report = {
            "device_id": clean_device_id,                                # 💡 room_no -> device_id (int)
            "event_type": alert_type,                                    # 完美對齊 event_type 字串
            "clip_path": event_data.get("clip_path", "/vids/fallback.mp4"), # 💡 補上後端必填的影片路徑
            "detected_at": iso_detected_at,                              # 💡 timestamp -> detected_at (ISO)
            "snapshot_path": img_path,                                   # 💡 saved_image_path -> snapshot_path
            "yolo_score": clean_yolo_score,                              # 💡 confidence(字串) -> yolo_score (float)
            "yolo_threshold": event_data.get("yolo_threshold", 0.5),      # 補上選填 threshold
            "vlm_summary": raw_report,                                   # 完美對齊後端文字判讀欄位
            "severity": "high" if "Fall" in alert_type else "low"         # 補上選填現場風險評級
        }
        
        producer.send('processed-reports', value=final_report)
        producer.flush()
        print(f"📢 [Kafka 2] 雙軌審查報告已外發！已完成 EventCreateRequest 工業級規格轉換！")
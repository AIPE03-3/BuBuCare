import json
import time
import requests
from kafka import KafkaConsumer, KafkaProducer

print("📦 [VLM 核心啟動] 正在連線地端 Kafka 與大模型引擎...")

# 1. 監聽前段 Kafka 1 (Topic: nursing-home-alerts)
consumer = KafkaConsumer(
    'nursing-home-alerts',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda v: json.loads(v.decode('utf-8')), 
    group_id='vlm-brain-cluster' # 支持多卡平行分流
)

# 2. 準備轉發到後段 Kafka 2 (Topic: processed-reports)
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

print("🚀 [護理長大腦上線] 正在監聽 Kafka Topic 1，進行雙軌分流審查（跌倒二審 + 環境巡檢）...")

for message in consumer:
    event_data = message.value
    
    # 讀取基礎封包資訊
    alert_type = event_data.get("alert_type", "Pending_VLM_Review")
    cam_id = event_data.get("room_no", "Unknown_Room") 
    env_clues = event_data.get("env_clues", "No specific objects")
    img_base64 = event_data.get("image_base64", "")
    confidence = event_data.get("confidence", "0.0%")
    alert_id = event_data.get("alert_id", f"ALT_{int(time.time())}")
    
    # =========================================================================
    # 🚦 依據 alert_type 進行動態 Prompt 分流切換
    # =========================================================================
    if alert_type == "Routine_Environment_Sanity_Check":
        print(f"\n[🔍 收到定時巡檢任務] 來自鏡頭：{cam_id}。VLM 正在主動巡房審查中...")
        
        prompt_text = (
            "You must reply ONLY in Traditional Chinese (繁體中文).\n"
            "You are an AI head nurse conducting a routine security check in a senior care center.\n"
            "Look at this room snapshot carefully and inspect if there are any potential environmental hazards, "
            "such as water spills on the floor, scattered obstacles blocking paths, or unbraked wheelchairs.\n\n"
            "Please output a structured environment report using this exact template:\n\n"
            "【安養中心智慧環境巡檢報告（定時自動版）】\n"
            "1. 巡檢狀態: 正常 / 發現潛在隱患\n"
            "2. 環境隱患檢查清單:\n"
            "   - 地面積水: (無 / 有，請說明位置)\n"
            "   - 動線障礙物: (無 / 有，請說明影響區域)\n"
            "   - 輪椅輔具安全: (正常 / 輪椅未拉煞車或擺放不當)\n"
            "3. 現場環境具體描述: (請詳細描述目前房間的整潔與安全狀況)\n"
            "4. 預防性護理建議: (若有隱患，請給出清潔或整理的提醒指令，若無則寫提防跌倒口訣)"
        )
        resolved_alert_type = "Sanity_Check_Resolved"
        
    else:
        print(f"\n[🔔 收到疑似跌倒警報] 來自鏡頭：{cam_id} (邊緣置信度：{confidence})。")
        print(f"🔍 正在對周遭環境物件 [{env_clues}] 進行多模態空間語意審查...")
        
        prompt_text = (
            "You must reply ONLY in Traditional Chinese (繁體中文).\n"
            "You are an AI head nurse in a senior care center. Look at this security snapshot carefully.\n"
            f"The edge environment scanning system just detected these objects nearby: {env_clues}.\n"
            "Analyze the image and the environment clues, evaluate the situation, and output a structured alert report using this exact template:\n\n"
            "【安養中心緊急通報（多模態環境感測二審版）】\n"
            "1. 狀況確認: (例如：確認發生長輩倒地事件 / 疑似誤報)\n"
            "2. 現場風險評級: (請評估並輸出：高風險 / 中風險 / 低風險)\n"
            f"3. AI 判讀信心度: (邊緣置信度為 {confidence}，請結合視覺畫面，主觀重新評估 0% 到 100% 的綜合分數)\n"
            "4. 現場畫面描述: (請用繁體中文詳細描述長輩倒地的姿勢，並結合環境線索描述現場狀況)\n"
            "5. 醫療建議行動: (請給出專業的護理派遣建議)"
        )
        resolved_alert_type = "Fall_With_VLM_Resolved"

    # =========================================================================
    # 🧠 呼叫 Ollama MiniCPM-V 模型推理
    # =========================================================================
    payload = {
        "model": "minicpm-v", 
        "prompt": prompt_text,
        "images": [img_base64],
        "stream": False
    }
    
    try:
        start_time = time.time()
        response = requests.post("http://localhost:11434/api/generate", json=payload)
        
        if response.status_code == 200:
            raw_report = response.json().get("response", "無法生成報告").strip()
            print(f"✨ [{cam_id}] VLM 處理完畢，耗時 {time.time() - start_time:.2f} 秒。")
            
            # 【相容性數據封包封裝】
            final_report = {
                "alert_id": alert_id,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "room_no": cam_id,
                "env_clues": env_clues,
                "confidence": confidence,
                "alert_type": resolved_alert_type,
                "vlm_summary": raw_report,  
                "vlm_report": raw_report,   
                "status": "UNREAD"
            }
            
            # 📢 灌入最後面的 Kafka 2 通道，交給後端即時 GUI 渲染
            producer.send('processed-reports', value=final_report)
            producer.flush()
            print(f"📢 [Kafka 2] 雙軌審查報告已外發至終端微服務通報中心！")
        else:
            print(f"❌ Ollama Server 錯誤代碼: {response.status_code}")
    except Exception as e:
        print(f"❌ 無法連線至 Ollama API 進行推理: {str(e)}")
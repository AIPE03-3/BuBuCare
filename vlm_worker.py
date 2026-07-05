import json
import time
import requests
from kafka import KafkaConsumer, KafkaProducer

print("📦 [VLM 核心啟動] 正在連線地端 Kafka 與大模型引擎...")

# 1. 監聽前段 Kafka 1 (Topic: nursing-home-alerts)
# 💡 將 value_serializer 修改為正確的 value_deserializer
consumer = KafkaConsumer(
    'nursing-home-alerts',
    bootstrap_servers=['localhost:9092'],
    value_deserializer=lambda v: json.loads(v.decode('utf-8')), 
    group_id='vlm-brain-cluster' # 設定消費者群組，支援多卡平行分流
)

# 2. 準備轉發到後段 Kafka 2 (Topic: processed-reports)
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

print("🚀 [護理長大腦上線] 正在監聽 Kafka Topic 1，排隊等待模糊事件二審...")

for message in consumer:
    event_data = message.value
    
    # 💡 對照 inference_test.py，發送端的 Key 是 "room_no" 而不是 "camera_id"
    cam_id = event_data.get("room_no", "Unknown_Room") 
    env_clues = event_data.get("env_clues", "No specific objects")
    img_base64 = event_data.get("image_base64", "")
    confidence = event_data.get("confidence", "0.0%")
    
    print(f"\n[🔔 收到模糊警報] 來自鏡頭：{cam_id} (邊緣置信度：{confidence})。")
    print(f"🔍 正在對周遭環境物件 [{env_clues}] 進行多模態空間語意審查...")
    
    # 呼叫地端 Ollama MiniCPM-V
    payload = {
        "model": "minicpm-v", 
        "prompt": (
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
        ),
        "images": [img_base64],
        "stream": False
    }
    
    try:
        start_time = time.time()
        response = requests.post("http://localhost:11434/api/generate", json=payload)
        
        if response.status_code == 200:
            raw_report = response.json().get("response", "無法生成報告").strip()
            print(f"✨ [{cam_id}] VLM 審查完畢，耗時 {time.time() - start_time:.2f} 秒。")
            
            # 💡 【終極相容性包裝】：
            # 同時寫入 "vlm_summary" 與 "vlm_report" 欄位，徹底解決後端 monitor 抓錯 Key 的精神分裂問題！
            final_report = {
                "alert_id": event_data.get("alert_id", f"ALT_{int(time.time())}"),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "room_no": cam_id,
                "env_clues": env_clues,
                "confidence": confidence,
                "alert_type": "Fall_With_VLM_Resolved",
                "vlm_summary": raw_report,  # 👈 同時填滿這兩個核心欄位
                "vlm_report": raw_report,   # 👈 確保不論後端等哪一個都不會拿到 None
                "status": "UNREAD"
            }
            
            # 📢 灌入最後面的 Kafka 2 (Topic: processed-reports)，讓通報端和資料庫收單
            producer.send('processed-reports', value=final_report)
            producer.flush()
            print(f"📢 [Kafka 2] 審查報告已成功外發至終端通報微服務！")
        else:
            print(f"❌ Ollama Server 錯誤代碼: {response.status_code}")
    except Exception as e:
        print(f"❌ 無法連線至 Ollama API 進行推理: {str(e)}")
import json
import time
from kafka import KafkaConsumer

# 監聽你的雙軌 Topic
# 快速道路: processed-reports / 慢速道路: nursing-home-alerts (或經 vlm 處理後的 topic)
consumer = KafkaConsumer(
    'processed-reports', 'nursing-home-alerts',
    bootstrap_servers=['localhost:9092'],
    auto_offset_reset='latest',
    value_deserializer=lambda x: json.loads(x.decode('utf-8'))
)

print("📊 [秒數差觀測站] 正在監聽 MLOps 管線數據...請觸發跌倒警報...")
print("================================================================")

try:
    for message in consumer:
        payload = message.value
        topic = message.topic
        arrival_time = time.time()  # 護理站接收到資料的當下時間
        
        edge_time = payload.get("edge_detect_time")
        alert_id = payload.get("alert_id", "Unknown")
        alert_type = payload.get("alert_type", "Unknown")
        
        if not edge_time:
            print(f"⚠️ 收到來自 {topic} 的封包，但裡面沒有埋 edge_detect_time 時間戳記，無法計算！")
            continue
            
        # 計算端到端總延遲（秒）
        total_latency_seconds = arrival_time - edge_time
        
        print(f"\n🔔 [擷取到警報事件] ID: {alert_id}")
        print(f"   📂 走哪條路: {'🧠 慢速道路 (VLM二審)' if 'VLM' in alert_type else '⚡ 快速道路 (純YOLO直發)'}")
        print(f"   ⏱️ 邊緣發出時間: {time.strftime('%H:%M:%S', time.localtime(edge_time))}.{int((edge_time%1)*1000):03d}")
        print(f"   ⏱️ 護理站收到時間: {time.strftime('%H:%M:%S', time.localtime(arrival_time))}.{int((arrival_time%1)*1000):03d}")
        print(f"   🚀 【總共花費時間】: {total_latency_seconds:.4f} 秒")
        print("----------------------------------------------------------------")

except KeyboardInterrupt:
    print("\n觀測結束。")
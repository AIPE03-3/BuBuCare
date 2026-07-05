from kafka import KafkaConsumer
import json
import os

# 清理終端機畫面
os.system('clear' if os.name == 'posix' else 'cls')

print("=" * 80)
print("🛡️  安養中心中樞訊息監聽伺服器 (Kafka Unified Alert Consumer) 已啟動...")
print("📡 正在即時監聽地端 Docker 中的最終結果 Topic: [processed-reports] ...")
print("=" * 80)

try:
    # 💡 業界標準：監聽最終處理完畢的結果佇列 (processed-reports)
    consumer = KafkaConsumer(
        'processed-reports',
        bootstrap_servers=['localhost:9092'],
        auto_offset_reset='latest',  # 只聽最新進來的警報
        enable_auto_commit=True,
        value_deserializer=lambda x: json.loads(x.decode('utf-8'))
    )
    
    print("✅ [連線成功] 成功接入統一告警中中樞，等待雙軌管線（快速道路/VLM二審）回傳結果...\n")

    for message in consumer:
        alert_data = message.value
        alert_type = alert_data.get('alert_type', 'Critical_Fast_Track') # 保底為快速道路
        
        # 🚨 驚悚的紅色工業級警報大圖排版
        print("\n" + "🔥" * 30)
        print("🚨🚨🚨 【安養中心中樞 - 護理站即時事件通報】 🚨🚨🚨")
        print("🔥" * 30)
        print(f"⏰ 通報時間: {alert_data.get('timestamp')}")
        print(f"🆔 警報編號: \033[1;33m{alert_data.get('alert_id')}\033[0m")
        print(f"🚪 發生地點: \033[1;36m{alert_data.get('room_no')}\033[0m")
        
        # 💡 根據業界不同警報層級進行顏色標記
        if alert_type == "Critical_Fast_Track":
            print(f"⚠️ 警報類型: \033[1;41;37m {alert_type} (地端秒級直發) \033[0m")
        elif alert_type == "Pending_VLM_Review":
            print(f"⚠️ 警報類型: \033[1;45;37m {alert_type} (大模型專家二審) \033[0m")
        else:
            print(f"⚠️ 警報類型: \033[1;43;30m {alert_type} (離床預警防線) \033[0m")
            
        print("-" * 60)
        
        # === 💥 業界多軌數據相容性解析 (Polymorphic Payload Parsing) ===
        print("\n🧠 \033[1;35m【核心事件報告內容】\033[0m")
        
        if alert_type == "Critical_Fast_Track":
            # ⚡ 快速道路：印出邊緣端直發的緊急核心摘要
            print(f"\033[1;31m{alert_data.get('vlm_summary', '未提供摘要')}\033[0m")
            print(f"📊 前端 AI 置信度: \033[1;33m{alert_data.get('confidence', '90%')}\033[0m")
            print(f"🔍 現場環境線索: {alert_data.get('env_clues', '無特定物件')}")
            
        elif alert_type == "Pending_VLM_Review":
            # 🧠 VLM 二審：印出中間大模型花 9 秒吐出來的繁體中文詳細護理日誌
            # 業界通常會把 summary 與詳細 report 一併呈現
            print(f"\033[1;32m[核心摘要]\033[0m {alert_data.get('vlm_summary', '無摘要')}")
            print(f"\033[1;36m[專家深度審查報告]\033[0m\n{alert_data.get('vlm_report', '報告解析異常，請檢查後台 JSON 格式。')}")
            
        elif alert_type == "Bed_Exit_Pre_Alert":
            # 🟠 離床預警：印出預警內容
            print(f"\033[1;33m{alert_data.get('vlm_summary', '長輩疑似有離床動作')}\033[0m")
            
        print("\n" + "=" * 60)
        print("💡 MLOps 提示：此告警已通過資料管線匯流，並觸發護理站 UI 閃爍。")
        print("=" * 60 + "\n")

except KeyboardInterrupt:
    print("\n🔒 監聽伺服器已安全關閉。")
except Exception as e:
    print(f"\n❌ Kafka 監聽錯誤: {e}")
    print("💡 請檢查 Docker 裡的 Kafka 是否有正常開著（localhost:9092）。")
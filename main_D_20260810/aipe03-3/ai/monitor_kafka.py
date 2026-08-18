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
    
    print("✅ [連線成功] 成功接入統一告警中樞，等待多軌管線（快速道路/VLM二審/離床/遊走/躁動/巡檢）回傳結果...\n")

    for message in consumer:
        alert_data = message.value
        alert_type = alert_data.get('alert_type', 'Critical_Fast_Track')
        
        # 🚨 紅色工業級警報大圖排版
        print("\n" + "🔥" * 30)
        print("🚨🚨🚨 【安養中心中樞 - 護理站即時事件通報】 🚨🚨🚨")
        print("🔥" * 30)
        print(f"⏰ 通報時間: {alert_data.get('timestamp')}")
        print(f"🆔 警報編號: \033[1;33m{alert_data.get('alert_id')}\033[0m")
        print(f"🚪 發生地點: \033[1;36m{alert_data.get('room_no')}\033[0m")
        
        # =========================================================================
        # 💡 根據業界不同警報層級進行顏色標記與分流顯示
        # =========================================================================
        if alert_type == "Critical_Fast_Track":
            print(f"⚠️ 警報類型: \033[1;41;37m {alert_type} (地端秒級直發 - 跌倒) \033[0m")
        elif alert_type == "Fall_With_VLM_Resolved":
            print(f"⚠️ 警報類型: \033[1;42;37m {alert_type} (大模型專家二審認證 - 跌倒) \033[0m")
        elif alert_type == "Bed_Exit_Pre_Alert":
            print(f"⚠️ 警報類型: \033[1;43;30m {alert_type} (離床預警防線) \033[0m")
        elif alert_type == "Wandering_Alert":
            print(f"⚠️ 警報類型: \033[1;45;37m {alert_type} (門口滯留遊走告警) \033[0m")
        elif alert_type == "Patient_Agitation_Alert":
            print(f"⚠️ 警報類型: \033[1;46;30m {alert_type} (夜間生理躁動預警) \033[0m")
        elif alert_type == "Sanity_Check_Resolved":
            print(f"⚠️ 警報類型: \033[1;44;37m {alert_type} (VLM 閒置算力自動巡檢) \033[0m")
        else:
            print(f"⚠️ 警報類型: \033[1;47;30m {alert_type} (未分類長照通報事件) \033[0m")
            
        print("-" * 60)
        
        # === 💥 多軌數據相容性解析 (Polymorphic Payload Parsing) ===
        print("\n🧠 \033[1;35m【核心事件報告內容】\033[0m")
        
        if alert_type == "Critical_Fast_Track":
            print(f"\033[1;31m{alert_data.get('vlm_summary', '未提供摘要')}\033[0m")
            print(f"📊 前端 AI 置信度: \033[1;33m{alert_data.get('confidence', '90%')}\033[0m")
            print(f"🔍 現場環境線索: {alert_data.get('env_clues', '無特定物件')}")
            if 'fusion_clue' in alert_data:
                print(f"🔊 多模態融合線索: \033[1;35m{alert_data.get('fusion_clue')}\033[0m")
            
        elif alert_type == "Fall_With_VLM_Resolved":
            print(f"\033[1;32m[專家深度審查報告]\033[0m\n{alert_data.get('vlm_report', '報告解析異常')}")
            print(f"🔍 現場環境線索: {alert_data.get('env_clues', '無特定物件')}")
            
        elif alert_type == "Sanity_Check_Resolved":
            print(f"\033[1;34m[智慧環境安全巡檢報告]\033[0m\n{alert_data.get('vlm_report', '巡檢報告生成異常')}")
            
        elif alert_type == "Bed_Exit_Pre_Alert":
            print(f"\033[1;33m{alert_data.get('vlm_summary', '長輩疑似有離床動作')}\033[0m")
            
        elif alert_type == "Wandering_Alert":
            print(f"\033[1;35m{alert_data.get('vlm_summary', '長輩在門口危險區域滯留')}\033[0m")
            
        elif alert_type == "Patient_Agitation_Alert":
            print(f"\033[1;36m{alert_data.get('vlm_summary', '床上長輩體位高頻掙扎')}\033[0m")
            
        else:
            print(f"{alert_data.get('vlm_summary', '無詳細通報內容')}")
            
        print("\n" + "=" * 60)
        print("💡 MLOps 提示：此告警已通過資料管線匯流，並觸發護理站 UI 閃爍。")
        print("=" * 60 + "\n")

except KeyboardInterrupt:
    print("\n🔒 監聽伺服器已安全關閉。")
except Exception as e:
    print(f"\n❌ Kafka 監聽錯誤: {e}")
    print("💡 請檢查 Docker 裡的 Kafka 是否有正常開著（localhost:9092）。")
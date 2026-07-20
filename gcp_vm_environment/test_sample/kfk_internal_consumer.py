# internal_consumer.py (在 Python 容器內執行)
from kafka import KafkaConsumer
import json

print("正在初始化內網 Consumer (免帳密)...")
consumer = KafkaConsumer(
    'test-topic',
    bootstrap_servers=['kafka:9092'],
    group_id='my_app_consumer_group',         # 消費者群組 ID (重開機靠這個認進度)
    auto_offset_reset='latest',               # 找不到進度時，從最新的資料開始讀
    #auto_offset_reset='earliest',            # 找不到進度時，從頭讀
    enable_auto_commit=False,                 # 關閉自動提交，改用手動提交確保安全
    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
    #consumer_timeout_ms=10000  # 10秒內沒新訊息就結束，方便測試, 
                               #不加這個參數：你必須在終端機手動按 Ctrl + C 才能結束測試。
                               #如果你想寫一個自動化腳本，執行完就看結果，程式會卡死無法自己結束
)

print("開始監聽 'test-topic'...")
#for message in consumer:
#    print(f"成功收到內網訊息: {message.value}")
    
try:
    # 2. 開始循環監聽訊息
    for message in consumer:
        print(f"收到訊息 - 關鍵字: {message.key}, 內容: {message.value}, 分區: {message.partition}, 位移: {message.offset}")
        
        try:
            # ---------------------------------------------
            # 在這裡寫您的業務邏輯 (例如：寫入資料庫、處理資料)
            # ---------------------------------------------
            print("資料處理成功！")
            
            # 3. 處理成功後，手動提交進度（Offset）
            consumer.commit()
            
        except Exception as e:
            print(f"處理訊息時發生錯誤: {e}")
            # 這裡可以決定要如何處理失敗的訊息（例如：記錄到 Log、丟進死信佇列 DLQ）

except KeyboardInterrupt:
    print("偵測到結束指令，正在關閉消費者...")
finally:
    # 4. 關閉連線，釋放資源
    consumer.close()
    print("消費者已安全關閉。")
    
    
'''
earliest從頭讀起。把 Topic 內現存的所有歷史舊資料全部補讀回來。資料報表計算、需要初始化完整資料庫、歷史資料不能漏掉的場景。
latest (預設)從最新讀起。不管過去的歷史資料，只讀取「App 啟動之後」才進來的新資料。即時通知、聊天室、儀表板監控（不在乎過去的歷史數據）。
'''
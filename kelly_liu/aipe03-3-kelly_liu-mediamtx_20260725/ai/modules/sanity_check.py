import time
import cv2
import os
from datetime import datetime

class RoutineSanityChecker:
    def __init__(self, camera_id, interval_seconds=15.0):
        self.camera_id = camera_id
        self.interval_seconds = interval_seconds
        self.last_check_time = time.time()

    def process(self, frame, ever_detected_fall, is_leaving_bed, is_wandering, producer):
        """平常沒事、無警報時，定時截圖外發 VLM 做環境巡檢"""
        current_time = time.time()
        
        # 只有在完全沒有任何警報觸發的「閒置時間」，才啟用 VLM 巡檢大腦
        if (current_time - self.last_check_time > self.interval_seconds) and \
           not ever_detected_fall and not is_leaving_bed and not is_wandering:
            
            self.last_check_time = current_time
            
            # 🧠 核心修正：跟 YOLO 一樣採用「動態不重複檔名」，帶上精確時間戳，防止硬碟實體相片被覆寫
            current_time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            snapshot_name = f"snapshot_{self.camera_id}_routine_{current_time_str}.jpg"
            
            cv2.imwrite(snapshot_name, frame)
            
            try:
                # 🧠 解析出數字 ID（例如 Room_301_Bed -> 301）
                try:
                    numeric_id = int(''.join(filter(str.isdigit, self.camera_id)))
                except ValueError:
                    numeric_id = 1
                
                routine_payload = {
                    "alert_id": f"RTN_{self.camera_id}_{int(current_time)}",
                    "device_id": numeric_id,                            # ✅ 新增：對齊後端要求的 integer ID
                    "event_type": "Routine_Environment_Sanity_Check",   # ✅ 修改：統一欄位名稱為 event_type
                    "detected_at": datetime.now().isoformat(),          # ✅ 新增：改用標準 ISO 時間字串
                    "camera_id": self.camera_id,                        # ✅ 修改：由 room_no 修正為統一的 camera_id
                    "yolo_score": 1.0,                                  # ✅ 新增：定時巡檢給予滿分置信度
                    "image_filename": snapshot_name,                    # ✅ 核心新增：精準傳遞不重複相片名稱，讓 VLM Worker 能物理命中
                    "severity": "low",                                  # ✅ 新增：巡檢嚴重度為低
                    "status": "PENDING_VLM_ROUTE"
                }
                
                if producer is not None:
                    # 發送到大模型審查通道，榨乾 VLM 閒置算力
                    producer.send('nursing-home-alerts', value=routine_payload)
                    producer.flush()
                    print(f"🔍 [模組 G] 已發送 [{self.camera_id}] 定時安全巡檢截圖（不重複命名：{snapshot_name}）至 VLM 佇列。")
                    return "Routine Checking..."
            except Exception as e:
                print(f"⚠️ [模組 G] 巡檢截圖發送失敗: {e}")
                
        return None
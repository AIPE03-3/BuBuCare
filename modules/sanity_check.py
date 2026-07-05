import time
import cv2
import base64

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
            
            # 將當前畫面編碼成 base64
            snapshot_name = f"routine_{self.camera_id}.jpg"
            cv2.imwrite(snapshot_name, frame)
            try:
                with open(snapshot_name, "rb") as img_file:
                    img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                
                routine_payload = {
                    "alert_id": f"RTN_{self.camera_id}_{int(current_time)}",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "room_no": self.camera_id,
                    "alert_type": "Routine_Environment_Sanity_Check",
                    "image_base64": img_base64,
                    "status": "PENDING_VLM_ROUTE"
                }
                
                if producer is not None:
                    # 發送到大模型審查通道，榨乾 VLM 閒置算力
                    producer.send('nursing-home-alerts', value=routine_payload)
                    producer.flush()
                    print(f"🔍 [模組 G] 已發送 [{self.camera_id}] 定時安全巡檢截圖至 VLM 佇列。")
                    return "Routine Checking..."
            except Exception as e:
                print(f"⚠️ [模組 G] 巡檢截圖發送失敗: {e}")
                
        return None
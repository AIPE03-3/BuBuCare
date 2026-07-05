import time

class WanderingDetector:
    def __init__(self, camera_id, threshold=8.0):
        self.camera_id = camera_id
        self.threshold = threshold
        self.stay_start_time = None
        self.wandering_alert_triggered = False

    def process(self, is_current_frame_valid, should_trigger_fall, ever_detected_fall, producer):
        """專職處理門口滯留遊走邏輯"""
        is_wandering = False

        if is_current_frame_valid and "Door" in self.camera_id and not should_trigger_fall and not ever_detected_fall:
            if self.stay_start_time is None:
                self.stay_start_time = time.time()
            
            stay_duration = time.time() - self.stay_start_time
            if stay_duration > self.threshold:
                is_wandering = True
        else:
            self.stay_start_time = None

        # Kafka 發送處理
        if is_wandering and not self.wandering_alert_triggered:
            self.wandering_alert_triggered = True
            wandering_payload = {
                "alert_id": f"WND_{self.camera_id}_{int(time.time())}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "room_no": self.camera_id,
                "alert_type": "Wandering_Alert",
                "vlm_summary": f"【長照預警系統：夜間異常遊走】感測到長輩在門口危險區域 [{self.camera_id}] 徘徊滯留已超過 {self.threshold} 秒，疑似有遊走或迷路風險，請值班護理人員前往關懷。",
                "status": "UNREAD"
            }
            if producer is not None:
                producer.send('processed-reports', value=wandering_payload)
                producer.flush()
                print(f"🟪 [{self.camera_id}] 偵測到門口異常滯留遊走！已外發通報。")

        return is_wandering
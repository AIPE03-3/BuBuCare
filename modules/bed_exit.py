import time

class BedExitDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.bed_alert_triggered = False

    def process(self, kp, bed_box_xyxy, img_h, is_physically_lying, producer):
        """專職處理半夜離床預警邏輯"""
        is_night_time = True
        is_leaving_bed = False

        # 核心圍籬判定
        if (is_night_time and 
            bed_box_xyxy is not None and 
            "Bed" in self.camera_id and 
            not is_physically_lying):
            
            bed_ymin, bed_ymax = bed_box_xyxy[1], bed_box_xyxy[3]
            left_ankle_y = kp[15][1] * img_h
            right_ankle_y = kp[16][1] * img_h
            
            bed_trigger_line = bed_ymin + (bed_ymax - bed_ymin) * 0.85
            if (left_ankle_y > bed_trigger_line and left_ankle_y != 0) or (right_ankle_y > bed_trigger_line and right_ankle_y != 0):
                is_leaving_bed = True

        # Kafka 發送處理
        if is_leaving_bed and not self.bed_alert_triggered:
            self.bed_alert_triggered = True
            bed_payload = {
                "alert_id": f"BED_{self.camera_id}_{int(time.time())}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "room_no": self.camera_id,        
                "alert_type": "Bed_Exit_Pre_Alert", 
                "vlm_summary": "【長照預警系統：半夜離床通知】邊緣圍籬感測到長輩雙腳已探出床沿，疑似正要起身離床。請值班護理人員提早前往協助，防範跌倒風險。",
                "status": "UNREAD"
            }
            if producer is not None:
                producer.send('processed-reports', value=bed_payload)
                producer.flush()
                print(f"🟠 [{self.camera_id}] 長輩半夜離床！已外發通報。")

        return is_leaving_bed
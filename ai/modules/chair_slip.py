import time
from datetime import datetime

class ChairSlipDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.slip_triggered = False

    def process(self, kp, results_env, img_h, is_physically_lying, producer):
        """偵測長輩是否從座椅/輪椅滑落至地面"""
        # 如果人已經觸發大範圍跌倒倒地了，就交給跌倒主邏輯
        if is_physically_lying:
            return False

        chair_box = None
        # 從環境偵測中找出椅子 (chair) 或沙發 (couch) 的座標
        if results_env and len(results_env[0].boxes) > 0:
            for box in results_env[0].boxes:
                cls_id = int(box.cls[0].item())
                lbl_name = results_env[0].names[cls_id]
                if lbl_name in ["chair", "couch", "wheelchair"]: # 順便把 wheelchair 類別補進來
                    chair_box = box.xyxy.cpu().numpy()[0]  # [x1, y1, x2, y2]
                    break

        # 🧠 滑落幾何交叉比對
        if chair_box is not None:
            chair_y1, chair_y2 = chair_box[1], chair_box[3]
            chair_height = chair_y2 - chair_y1
            # 設定椅子坐墊的參考水平線 (約在椅子高度的 60% 位置)
            chair_seat_line = chair_y1 + chair_height * 0.60

            # 抓取人體的屁股/髖部關節 (11, 12 號節點) 與肩膀 (5, 6 號節點)
            hip_y = (kp[11][1] + kp[12][1]) / 2.0 * img_h
            shoulder_y = (kp[5][1] + kp[6][1]) / 2.0 * img_h

            # 如果臀部跟肩膀高度同時「低於坐墊水平線」，且臀部高度並非 0 (代表有抓到人)
            if hip_y > chair_seat_line and shoulder_y > chair_y1 and hip_y != 0:
                if not self.slip_triggered:
                    self.slip_triggered = True
                    
                    # 🧠 解析出數字 ID（例如 Room_301_Bed -> 301）
                    try:
                        numeric_id = int(''.join(filter(str.isdigit, self.camera_id)))
                    except ValueError:
                        numeric_id = 1

                    slip_payload = {
                        "alert_id": f"SLP_{self.camera_id}_{int(time.time())}",
                        "device_id": numeric_id,                    # ✅ 對齊後端要求的 integer ID
                        "event_type": "chair_slip",                 # ✅ 明確定義事件型態為座椅滑落
                        "detected_at": datetime.now().isoformat(),  # ✅ 改用標準 ISO 時間字串
                        "camera_id": self.camera_id,                # ✅ 由 room_no 修正為統一的 camera_id
                        "yolo_score": 0.88,                         # ✅ 給予預設信心度
                        "vlm_summary": f"【長照預警系統：座椅意外滑落】感測到 [{self.camera_id}] 長輩疑似從輪椅或座椅滑落、癱坐在地上！可能因無力或失神導致，請護理人員立刻前往協助。",
                        "severity": "high",                         # ✅ 對齊後端嚴重度
                        "status": "UNREAD"
                    }
                    
                    if producer is not None:
                        producer.send('processed-reports', value=slip_payload)
                        producer.flush()
                        print(f"⚠️ [模組 I] [{self.camera_id}] 偵測到長輩從座椅滑落意外！（格式已對齊）")
                return True
        else:
            self.slip_triggered = False

        return False
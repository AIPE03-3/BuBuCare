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
                    # ⚠️ 契約邊界：本模組「只偵測、不外發」。
                    # 座椅滑落事件的 Kafka 外發統一由 inference_test 主迴圈負責
                    # （is_chair_slipped=True → route_by_confidence() 組出恰好 9 欄的
                    #   processed-reports payload：device_id/event_type/clip_path/detected_at/
                    #   snapshot_path/yolo_score/yolo_threshold/vlm_summary/severity）。
                    # 早期版本曾在此直接 producer.send() 一份自訂 payload（多 alert_id/camera_id/
                    # status、缺 clip_path/snapshot_path/yolo_threshold），會被後端 422 退件、
                    # 且與主迴圈重複外發。移除後改回傳 True 交給主迴圈，守住 9 欄契約。
                    print(f"⚠️ [模組 I] [{self.camera_id}] 偵測到長輩從座椅滑落意外！（交主迴圈外發）")
                return True
        else:
            self.slip_triggered = False

        return False
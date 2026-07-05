import numpy as np
import time

class MicroMotionDetector:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        # 儲存過去數影格的骨架中心點，用來算標準差
        self.motion_history = []
        self.agitation_triggered = False

    def process(self, kp, is_physically_lying, producer):
        """偵測半夜躺在床上長輩的微觀動作 (躁動偵測)"""
        if "Bed" not in self.camera_id or not is_physically_lying:
            return False

        # 擷取上半身骨架核心節點 (鼻子、雙肩、雙髖) 的平均座標作為重心
        core_pts = kp[[0, 5, 6, 11, 12], :2]
        valid_pts = core_pts[~np.all(core_pts == 0, axis=1)]
        
        if len(valid_pts) > 0:
            center_pt = np.mean(valid_pts, axis=0)
            self.motion_history.append(center_pt)
            if len(self.motion_history) > 45:  # 維持一個短時序視窗
                self.motion_history.pop(0)

            if len(self.motion_history) >= 30:
                # 計算中心點的時序標準差 (震盪幅度)
                history_np = np.array(self.motion_history)
                std_x = np.std(history_np[:, 0])
                std_y = np.std(history_np[:, 1])
                total_deviation = std_x + std_y

                # 💡 閾值設定：大於 0.045 代表在床上高頻率劇烈晃動、掙扎
                if total_deviation > 0.045:
                    if not self.agitation_triggered:
                        self.agitation_triggered = True
                        agitation_payload = {
                            "alert_id": f"AGT_{self.camera_id}_{int(time.time())}",
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                            "room_no": self.camera_id,
                            "alert_type": "Patient_Agitation_Alert",
                            "vlm_summary": f"【長照預警系統：夜間身體躁動】感測到 [{self.camera_id}] 床上長輩體位出現異常高頻掙扎或躁動，疑似身體不適，請前往關懷。",
                            "status": "UNREAD"
                        }
                        if producer is not None:
                            producer.send('processed-reports', value=agitation_payload)
                            producer.flush()
                            print(f"🚨 [模組 F] [{self.camera_id}] 偵測到夜間異常躁動掙扎！")
                    return True
                else:
                    self.agitation_triggered = False
        return False
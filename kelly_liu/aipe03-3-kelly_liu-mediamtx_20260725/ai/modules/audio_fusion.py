import random
import time

class AudioFusionEngine:
    def __init__(self, camera_id):
        self.camera_id = camera_id
        self.last_audio_simulation = time.time()

    def listen_and_fuse(self, should_trigger_fall, act_confidence):
        """音訊視覺雙軌特徵融合：影像抓不到死角，用耳朵聽"""
        audio_keyword = None
        current_time = time.time()

        # 💡 展示模擬邏輯：每隔 22 秒，Room_303 隨機模擬傳出「撞擊聲」或「救命大喊」
        if "303" in self.camera_id and (current_time - self.last_audio_simulation > 22.0):
            self.last_audio_simulation = current_time
            audio_keyword = random.choice(["THUD_CRASH", "HELP_SCREAM"])
            print(f"\n📢 [🔊 聽覺感測器] 頻道 [{self.camera_id}] 捕捉到環境異常爆發音：{audio_keyword} !!")

        # === 🧠 雙模態權重融合決策樹 ===
        fused_trigger = should_trigger_fall
        fused_confidence = act_confidence
        fusion_reason = None

        if audio_keyword is not None:
            # 情況 A：影像還在猶豫（信心低），但耳朵聽到劇烈撞擊或呼救 ── 強制融合升級為跌倒！
            if not should_trigger_fall or act_confidence < 0.60:
                fused_trigger = True
                
                # 🎯 下午實戰聯調重要小秘訣：
                # 如果你想讓音訊觸發後走「快車道」(直接送後端)，維持 0.96。
                # 如果你想讓音訊觸發後走「慢車道」(送 VLM 二審)，請在現場把這行改成 0.85。
                fused_confidence = 0.96  
                
                # 為了避免跟後端原本認得的單純 fall 打架，把 fusion_reason 寫進環境線索中
                fusion_reason = f"Audio-Visual Fused (Detected {audio_keyword} while person down)"
                print(f"🔥 [多模態智導中樞] 視覺置信度不足（原 {act_confidence:.2f}），聽覺特徵加權介入！強行判定為真實跌倒，更新置信度為: {fused_confidence}")

        return fused_trigger, fused_confidence, fusion_reason
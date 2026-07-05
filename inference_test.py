import cv2
import torch
import numpy as np
from collections import deque
from ultralytics import YOLO
import torch.nn as nn
import os
import threading
import json
import time
from datetime import datetime  
import base64

# =========================================================================
# 🌟 導入全套自研長照智慧模組（六大防線極致完全體對照表）
# =========================================================================
from modules.bed_exit import BedExitDetector         # 模組 A：半夜離床虛擬圍籬預警
from modules.wandering import WanderingDetector       # 模組 E：跨相機軌跡徘徊遊走偵測
from modules.sanity_check import RoutineSanityChecker  # 模組 G：VLM 閒置算力環境安全巡檢
from modules.micro_motion import MicroMotionDetector   # 模組 F：非接觸式床上微觀躁動偵測
from modules.audio_fusion import AudioFusionEngine     # 模組 H：邊緣端聽覺多模態特徵融合
from modules.chair_slip import ChairSlipDetector       # 模組 I：座椅/輪椅意外滑落偵測

# =========================================================================
# 🛠️ MLOps 基礎建設：Kafka 初始化
# =========================================================================
from kafka import KafkaProducer

try:
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    print("✅ [Kafka] 訊息中心連線成功！雙向數據管線已就緒。")
except Exception as e:
    print(f"⚠️ [Kafka] 連線失敗（警報將無法外發）: {e}")
    producer = None

device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
print(f"🚀 推理引擎啟動，硬體加速裝置：{device}")

# =========================================================================
# 🌟 Action Transformer 模型架構
# =========================================================================
class ActionTransformer(nn.Module):
    def __init__(self, input_dim=34, seq_len=30, num_classes=2):
        super(ActionTransformer, self).__init__()
        self.embedding = nn.Linear(input_dim, 64)
        encoder_layer = nn.TransformerEncoderLayer(d_model=64, nhead=4, dim_feedforward=128, batch_first=True)
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=2)
        self.fc = nn.Sequential(
            nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, num_classes)
        )
    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        return self.fc(x.mean(dim=1))

# =========================================================================
# 📦 全域載入官方模型與時序模型（✅ 已升級為 YOLO-Seg 實例分割）
# =========================================================================
print("📦 正在載入官方 YOLO11s 家族模型與自研 Action Transformer...")
yolo_pose_model = YOLO("yolo11s-pose.pt") 
yolo_env_model = YOLO("yolo11s-seg.pt")   # 👈 核心修改：正式切換為實例分割模型！

# 如果沒有權重檔，先模擬測試，避免程式崩潰
if os.path.exists("action_transformer.pth"):
    transformer_model = ActionTransformer().to(device)
    transformer_model.load_state_dict(torch.load("action_transformer.pth", map_location=device))
    transformer_model.eval()
    print("🔥 所有模型載入成功，多任務平行化管線就緒！")
else:
    print("⚠️ 找不到 action_transformer.pth，將使用模擬機制運行時序推理。")
    transformer_model = None

output_frames = {}
frames_lock = threading.Lock()

# =========================================================================
# 📹 核心：多鏡頭平行巡邏的 Edge Worker
# =========================================================================
def camera_worker(camera_id, video_source):
    global producer, device, yolo_pose_model, yolo_env_model, transformer_model, output_frames, frames_lock
    
    print(f"🚀 鏡頭頻道 [{camera_id}] 啟動拉流：{video_source}")
    cap = cv2.VideoCapture(video_source)
    if not cap.isOpened(): 
        print(f"❌ 鏡頭頻道 [{camera_id}] 無法開啟影像源: {video_source}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps): fps = 30.0
    frame_delay = 1.0 / fps  

    frame_window = deque(maxlen=30)
    vlm_triggered = False
    vlm_report = "Waiting for alert..."
    
    last_pose_feat = np.zeros(34, dtype=np.float32)
    has_seen_person = False
    last_valid_annotated_frame = None  
    frame_count = 0
    normal_h_reference = None
    
    # 💡 狀態旗標
    ever_detected_fall = False  # 模組 C：全域歷史記憶鎖旗標
    
    # 💡 實例化全套獨立的外掛大腦物件
    bed_detector = BedExitDetector(camera_id)
    wandering_detector = WanderingDetector(camera_id, threshold=8.0)
    sanity_checker = RoutineSanityChecker(camera_id, interval_seconds=15.0)
    motion_detector = MicroMotionDetector(camera_id)
    audio_engine = AudioFusionEngine(camera_id)
    chair_slitter = ChairSlipDetector(camera_id)  # 模組 I：座椅滑落實例物件

    while True:
        t_start = time.time()
        ret, frame = cap.read()
        
        if not ret:
            print(f"⏳ [{camera_id}] 影像流讀取結束，強行等待後端 MLOps 管線與 VLM 二審完成...")
            time.sleep(12) 
            with frames_lock: backup_frame = output_frames.get(camera_id, None)
            final_base = backup_frame if backup_frame is not None else last_valid_annotated_frame
            if final_base is not None:
                h, w, _ = final_base.shape
                final_color = (0, 0, 255) if ever_detected_fall else (0, 255, 0)
                final_text = "FALL DETECTED! (Fixed End)" if ever_detected_fall else "Normal (Stream End)"
                clean_end_frame = final_base.copy()
                cv2.rectangle(clean_end_frame, (0, 0), (w, h), final_color, 15)
                cv2.rectangle(clean_end_frame, (35, 20), (600, 80), (0, 0, 0), -1)
                cv2.putText(clean_end_frame, final_text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, final_color, 3, cv2.LINE_AA)
                cv2.putText(clean_end_frame, "STREAM END", (int(w/2) - 180, int(h/2)), cv2.FONT_HERSHEY_SIMPLEX, 1.8, final_color, 5, cv2.LINE_AA)
                with frames_lock: output_frames[camera_id] = clean_end_frame
            break

        frame_count += 1
        if frame_count % 2 != 0:
            if last_valid_annotated_frame is not None:
                with frames_lock: output_frames[camera_id] = last_valid_annotated_frame.copy()
            t_sleep = frame_delay - (time.time() - t_start)
            if t_sleep > 0: time.sleep(t_sleep)
            continue

        img_h, img_w, _ = frame.shape
        
        # 核心推理：同時運行 Pose 與 Seg 模型
        results_pose = yolo_pose_model(frame, verbose=False, conf=0.45)
        results_env = yolo_env_model(frame, verbose=False, conf=0.35)  # 執行實例分割
        
        detected_objects = []
        bed_box_xyxy = None  
        
        # 👈 核心修改：利用 YOLO-Seg 的方式解析不規則輪廓與物件
        if results_env and len(results_env[0].boxes) > 0:
            for i, box in enumerate(results_env[0].boxes):
                cls_id = int(box.cls[0].item())
                lbl_name = yolo_env_model.names[cls_id]
                
                # 篩選長照中心核心目標環境物件 (新增不規則類別如被子、水漬等擴充，此處維持你的基礎列表)
                if lbl_name in ["wheelchair", "bed", "chair", "couch", "bottle", "cup"] and lbl_name not in detected_objects:
                    detected_objects.append(lbl_name)
                    
                if lbl_name == "bed": 
                    bed_box_xyxy = box.xyxy.cpu().numpy()[0]
                    
        current_pose_feat = np.zeros(34, dtype=np.float32)
        is_current_frame_valid = False
        is_physically_lying = False  
        is_occluded_fall = False     
        is_leaving_bed = False       
        is_wandering = False  
        is_agitated = False
        is_chair_slipped = False  
        
        if results_pose and len(results_pose[0].keypoints) > 0:
            kpts_obj = results_pose[0].keypoints
            try:
                kpts_data = kpts_obj.xyn.cpu().numpy() 
                conf_data = results_pose[0].boxes.conf.cpu().numpy()  
                boxes_data = results_pose[0].boxes.xywh.cpu().numpy()  
                boxes_xyxy = results_pose[0].boxes.xyxy.cpu().numpy()
                
                if kpts_data.ndim == 3 and kpts_data.shape[0] > 0:
                    best_idx = -1; max_score = -1.0  
                    for idx in range(kpts_data.shape[0]):
                        if idx < len(conf_data) and conf_data[idx] < 0.45: continue
                        if idx < len(boxes_data):
                            _, _, w_box, h_box = boxes_data[idx]
                            score = conf_data[idx] * (w_box * h_box)
                            if score > max_score: max_score = score; best_idx = idx
                    
                    if best_idx != -1:
                        kp = kpts_data[best_idx]  
                        temp_feat = kp[:17, :2].flatten()
                        if not np.all(temp_feat == 0):
                            current_pose_feat = temp_feat.copy(); last_pose_feat = current_pose_feat.copy()
                            has_seen_person = True; is_current_frame_valid = True  
                        
                        _, _, w_box, h_box = boxes_data[best_idx]
                        x1, y1, x2, y2 = boxes_xyxy[best_idx]
                        if normal_h_reference is None and frame_count > 10 and frame_count < 40: normal_h_reference = h_box
                            
                        # 跌倒防線 A
                        try:
                            shoulder_x = (kp[5][0] + kp[6][0]) / 2.0; shoulder_y = (kp[5][1] + kp[6][1]) / 2.0
                            hip_x = (kp[11][0] + kp[12][0]) / 2.0; hip_y = (kp[11][1] + kp[12][1]) / 2.0
                            if not (shoulder_x == 0 or hip_x == 0):
                                body_angle = np.abs(np.degrees(np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x)))
                                if body_angle < 40.0 or (w_box / h_box) > 1.25: is_physically_lying = True
                        except Exception: pass
                            
                        # 跌倒防線 B (幾何遮擋防禦)
                        if normal_h_reference is not None:
                            if (h_box / normal_h_reference) < 0.70 and y2 > (img_h * 0.5): is_occluded_fall = True
                                
                        # 模組 A：離床預警呼叫
                        is_leaving_bed = bed_detector.process(kp, bed_box_xyxy, img_h, is_physically_lying, producer)
                        
                        # 模組 F：床上微觀躁動呼叫
                        is_agitated = motion_detector.process(kp, is_physically_lying, producer)
                        
                        # 模組 I：座椅/輪椅意外滑落呼叫
                        is_chair_slipped = chair_slitter.process(kp, results_env, img_h, is_physically_lying, producer)

            except Exception: pass

        if not is_current_frame_valid and has_seen_person: current_pose_feat = last_pose_feat.copy()

        # === 時序 Transformer 核心推理 ===
        frame_window.append(current_pose_feat)
        status_text = "Normal"; color = (0, 255, 0); act_confidence = 0.0; draw_border = True   
        pred_class = 1  
        
        if len(frame_window) == 30 and transformer_model is not None:
            np_window = np.array(frame_window, dtype=np.float32)
            input_tensor = torch.from_numpy(np_window).unsqueeze(0).to(device)
            with torch.no_grad():
                outputs = transformer_model(input_tensor)
                prob = torch.softmax(outputs, dim=1)
                pred_class = torch.argmax(prob, dim=1).item()
                act_confidence = prob[0][pred_class].item()
        elif len(frame_window) == 30:
            pred_class = 0 if is_physically_lying else 1
            act_confidence = 0.75 if is_physically_lying else 0.0

        is_ai_thinking_fall = (pred_class == 0 and act_confidence > 0.35) if len(frame_window) == 30 else False
        should_trigger_fall = False
        if has_seen_person:
            if is_physically_lying or is_occluded_fall:  
                if len(frame_window) < 30 or is_ai_thinking_fall or is_occluded_fall: should_trigger_fall = True
            elif len(frame_window) == 30 and pred_class == 0 and act_confidence > 0.55: should_trigger_fall = True

        # === 模組 H：多模態音訊特徵融合運算 ===
        should_trigger_fall, act_confidence, fusion_reason = audio_engine.listen_and_fuse(should_trigger_fall, act_confidence)
        if fusion_reason is not None:
            vlm_report = "Audio Fused!"

        # 模組 E：滯留遊走呼走
        is_wandering = wandering_detector.process(is_current_frame_valid, should_trigger_fall, ever_detected_fall, producer)

        # 模組 G：環境安全巡檢定時器呼叫
        check_status = sanity_checker.process(frame, ever_detected_fall, is_leaving_bed, is_wandering, producer)
        if check_status is not None:
            vlm_report = check_status

        # =========================================================================
        # 🚦 終極決策中樞
        # =========================================================================
        if should_trigger_fall or ever_detected_fall or is_chair_slipped:
            status_text = "FALL / CHAIR SLIP DETECTED!" if is_chair_slipped else "FALL DETECTED!"
            color = (0, 0, 255) 
            ever_detected_fall = True 

        elif is_leaving_bed:
            status_text = "BED EXIT PRE-ALERT"
            color = (0, 165, 255) 

        elif is_agitated:
            status_text = "PATIENT AGITATION (夜間躁動)"
            color = (0, 255, 255) 

        elif is_wandering:
            status_text = "WANDERING ALERT (門口滯留遊走)"
            color = (255, 0, 255) 

        else:
            if len(frame_window) < 30:
                status_text = "Buffering..."; color = (0, 255, 255); draw_border = False   
            else:
                status_text = "Normal"; color = (0, 255, 0)

        # =========================================================================
        # ⚡ 跌倒雙軌分流發送與基準時間戳標記
        # =========================================================================
        if (should_trigger_fall or is_chair_slipped) and not vlm_triggered:
            env_clues_str = ", ".join(detected_objects) if detected_objects else "No specific objects"
            edge_detect_time = time.time() 
            
            alert_payload = {
                "alert_id": f"ALT_{camera_id}_{int(edge_detect_time * 1000)}",
                "label": "chair_slip" if is_chair_slipped else "fall", 
                "edge_detect_time": edge_detect_time,                 
                "vlm_process_done_time": None,                        
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(edge_detect_time)),
                "room_no": camera_id,        
                "env_clues": env_clues_str,
                "confidence": f"{act_confidence*100:.1f}%" if act_confidence > 0 else "70.0%"
            }
            if fusion_reason:
                alert_payload["fusion_clue"] = fusion_reason

            if producer is not None:
                if (act_confidence > 0.90 or is_chair_slipped) and not is_occluded_fall:
                    vlm_triggered = True
                    alert_payload["alert_type"] = "Critical_Fast_Track"
                    alert_payload["vlm_summary"] = "【緊急通報】邊緣端偵測到輪椅意外滑落/嚴重跌倒！請立刻前往救援。"
                    alert_payload["status"] = "UNREAD"
                    producer.send('processed-reports', value=alert_payload)
                    producer.flush()
                    vlm_report = "Fast-track Sent"
                else:
                    vlm_triggered = True
                    alert_payload["alert_type"] = "Pending_VLM_Review"
                    snapshot_name = f"snapshot_{camera_id}.jpg"
                    cv2.imwrite(snapshot_name, frame)
                    with open(snapshot_name, "rb") as img_file:
                        img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                    alert_payload["image_base64"] = img_base64
                    producer.send('nursing-home-alerts', value=alert_payload)
                    producer.flush()
                    vlm_report = "VLM Queued..."

        # === Step D: 畫布渲染（✅ 自動半透明疊加不規則物件輪廓） ===
        annotated_frame = results_pose[0].plot(boxes=True, labels=True, conf=0.45) 
        
        # 👈 核心修改：在畫布上動態疊加 YOLO-Seg 的彩色半透明不規則輪廓
        if results_env and getattr(results_env[0], 'masks', None) is not None:
            masks = results_env[0].masks.data.cpu().numpy()
            for i, mask in enumerate(masks):
                cls_id = int(results_env[0].boxes.cls[i].item())
                lbl_name = yolo_env_model.names[cls_id]
                
                if lbl_name in ["wheelchair", "bed", "chair", "couch", "bottle", "cup"]:
                    # 將 Mask 縮放回原始影像尺寸
                    mask_resized = cv2.resize(mask, (img_w, img_h))
                    # 建立綠色遮罩圖層
                    color_mask = np.zeros_like(frame, dtype=np.uint8)
                    color_mask[mask_resized > 0.5] = [0, 255, 0] # 綠色實例輪廓
                    # 以 0.4 的透明度疊加到主畫面
                    annotated_frame = cv2.addWeighted(annotated_frame, 1.0, color_mask, 0.4, 0)

        if draw_border: cv2.rectangle(annotated_frame, (0, 0), (img_w, img_h), color, 12)
        cv2.putText(annotated_frame, status_text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)
        cv2.putText(annotated_frame, f"VLM Status: {vlm_report}", (40, img_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        
        if is_current_frame_valid: last_valid_annotated_frame = annotated_frame.copy()
        with frames_lock: output_frames[camera_id] = annotated_frame.copy()

        t_elapsed = time.time() - t_start
        t_sleep = frame_delay - t_elapsed
        if t_sleep > 0: time.sleep(t_sleep)

    cap.release()

# =========================================================================
# 🏢 主執行緒專職 GUI 與排列控制
# =========================================================================
if __name__ == "__main__":
    camera_channels = {
        "Room_301_Bed": "test_demo/test1.mp4",        
    }
    print(f"🎬 全連鎖安養中心多鏡頭多模態智能管線全面啟動（YOLO-Seg模式啟用）...")
    
    threads = []
    for cam_id, stream_src in camera_channels.items():
        t = threading.Thread(target=camera_worker, args=(cam_id, stream_src))
        t.daemon = True; threads.append(t); t.start()
        
    try:
        frame_interval = 1.0 / 30.0; window_positions = {}  
        while True:
            start_time = time.time(); active_windows = False
            with frames_lock: current_display_frames = output_frames.copy()
                
            for idx, (cam_id, img_to_show) in enumerate(current_display_frames.items()):
                if img_to_show is not None:
                    win_name = f"Fall Detection System - {cam_id}"
                    cv2.imshow(win_name, img_to_show)
                    if win_name not in window_positions:
                        x_pos = 50 + (idx * 660); y_pos = 70
                        cv2.moveWindow(win_name, x_pos, y_pos)
                        window_positions[win_name] = (x_pos, y_pos)
                    active_windows = True
            
            if active_windows:
                if cv2.waitKey(1) & 0xFF == ord('q'): break
            
            sleep_time = frame_interval - (time.time() - start_time)
            time.sleep(sleep_time if sleep_time > 0 else 0.001)
                
    except KeyboardInterrupt: pass
    finally:
        cv2.destroyAllWindows()
        if producer is not None: producer.close()
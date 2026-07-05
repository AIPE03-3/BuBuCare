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

# 1. 啟用硬體加速
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
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, num_classes)
        )
        
    def forward(self, x):
        x = self.embedding(x)
        x = self.transformer(x)
        x = x.mean(dim=1)
        return self.fc(x)

# =========================================================================
# 📦 全域載入雙軌 YOLO11s 家族模型與時序模型
# =========================================================================
print("📦 正在載入官方 YOLO11s-Pose 與自研 Action Transformer...")
yolo_pose_model = YOLO("yolo11s-pose.pt") 
yolo_env_model = YOLO("yolo11s.pt") 

transformer_model = ActionTransformer().to(device)
transformer_model.load_state_dict(torch.load("action_transformer.pth", map_location=device))
transformer_model.eval()
print("🔥 所有模型載入成功，多任務平行化管線就緒！")

# 💡 全域共享字典與鎖
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
        print(f"❌ [{camera_id}] 無法開啟影片源：{video_source}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps):
        fps = 30.0
    frame_delay = 1.0 / fps  

    frame_window = deque(maxlen=30)
    vlm_triggered = False
    bed_alert_triggered = False      
    vlm_report = "Waiting for alert..."
    
    last_pose_feat = np.zeros(34, dtype=np.float32)
    has_seen_person = False
    last_valid_annotated_frame = None  
    frame_count = 0
    normal_h_reference = None
    occluded_frames_counter = 0  
    
    # 💡 全域歷史記憶鎖，只要這部影片「曾經跌倒過」，就鎖定為 True
    ever_detected_fall = False  

    while True:
        t_start = time.time()
        ret, frame = cap.read()
        
        # 💡 影片播放完畢的定格與管線續命邏輯
        if not ret:
            print(f"⏳ [{camera_id}] 影像流讀取結束，強行等待後端 MLOps 管線與 VLM 二審完成...")
            
            # === 💥 核心修正：給後端 VLM 專家二審 12 秒的推理與傳輸緩衝時間 ===
            time.sleep(12) 
            
            with frames_lock:
                backup_frame = output_frames.get(camera_id, None)
            final_base = backup_frame if backup_frame is not None else last_valid_annotated_frame
            
            if final_base is not None:
                h, w, _ = final_base.shape
                
                # 只要這部影片中途有紅過，定格就是紅，絕對不退色！
                if ever_detected_fall:
                    final_color = (0, 0, 255) # 🔴 紅色
                    final_text = "FALL DETECTED! (Fixed End)"
                else:
                    final_color = (0, 255, 0) # 🟢 綠色
                    final_text = "Normal (Stream End)"
                
                clean_end_frame = final_base.copy()
                cv2.rectangle(clean_end_frame, (0, 0), (w, h), final_color, 15)
                
                # 畫黑底矩形遮罩，乾淨清除歷史 Normal 疊字
                cv2.rectangle(clean_end_frame, (35, 20), (600, 80), (0, 0, 0), -1)
                cv2.putText(clean_end_frame, final_text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, final_color, 3, cv2.LINE_AA)
                cv2.putText(clean_end_frame, "STREAM END", (int(w/2) - 180, int(h/2)), 
                            cv2.FONT_HERSHEY_SIMPLEX, 1.8, final_color, 5, cv2.LINE_AA)
                
                # 將最終畫面寫入後直接 break 結束 Worker 執行緒，讓主線程安全收尾
                with frames_lock:
                    output_frames[camera_id] = clean_end_frame
                print(f"🏁 [{camera_id}] Worker 任務完成，安全退場。")
            break

        frame_count += 1
        
        if frame_count % 2 != 0:
            if last_valid_annotated_frame is not None:
                with frames_lock:
                    output_frames[camera_id] = last_valid_annotated_frame.copy()
            t_elapsed = time.time() - t_start
            t_sleep = frame_delay - t_elapsed
            if t_sleep > 0: time.sleep(t_sleep)
            continue

        img_h, img_w, _ = frame.shape

        # === Step 1: 前端人體視覺感測 ===
        results_pose = yolo_pose_model(frame, verbose=False, conf=0.45)
        
        # === Step 2: 前端環境物件感測 ===
        results_env = yolo_env_model(frame, verbose=False, conf=0.35)
        detected_objects = []
        bed_box_xyxy = None  
        
        if results_env and len(results_env[0].boxes) > 0:
            for box in results_env[0].boxes:
                cls_id = int(box.cls[0].item())
                lbl_name = yolo_env_model.names[cls_id]
                if lbl_name in ["wheelchair", "bed", "chair", "couch", "bottle", "cup"] and lbl_name not in detected_objects:
                    detected_objects.append(lbl_name)
                if lbl_name == "bed":
                    bed_box_xyxy = box.xyxy.cpu().numpy()[0]
        
        current_pose_feat = np.zeros(34, dtype=np.float32)
        is_current_frame_valid = False
        is_physically_lying = False  
        is_occluded_fall = False     
        is_leaving_bed = False       
        
        if results_pose and len(results_pose[0].keypoints) > 0:
            kpts_obj = results_pose[0].keypoints
            try:
                kpts_data = kpts_obj.xyn.cpu().numpy() 
                conf_data = results_pose[0].boxes.conf.cpu().numpy()  
                boxes_data = results_pose[0].boxes.xywh.cpu().numpy()  
                boxes_xyxy = results_pose[0].boxes.xyxy.cpu().numpy()
                
                if kpts_data.ndim == 3 and kpts_data.shape[0] > 0:
                    best_idx = -1  
                    max_score = -1.0  
                    
                    for idx in range(kpts_data.shape[0]):
                        if idx < len(conf_data) and conf_data[idx] < 0.45: continue
                        if idx < len(boxes_data):
                            x_center, y_center, w_box, h_box = boxes_data[idx]
                            score = conf_data[idx] * (w_box * h_box)
                            if score > max_score:
                                max_score = score
                                best_idx = idx
                    
                    if best_idx != -1:
                        kp = kpts_data[best_idx]  
                        temp_feat = kp[:17, :2].flatten()
                        if not np.all(temp_feat == 0):
                            current_pose_feat = temp_feat.copy()
                            last_pose_feat = current_pose_feat.copy()
                            has_seen_person = True
                            is_current_frame_valid = True  
                        
                        _, _, w_box, h_box = boxes_data[best_idx]
                        x1, y1, x2, y2 = boxes_xyxy[best_idx]
                        
                        if normal_h_reference is None and frame_count > 10 and frame_count < 40:
                            normal_h_reference = h_box
                            
                        # 跌倒防線 A：純骨架脊椎角度
                        try:
                            shoulder_x = (kp[5][0] + kp[6][0]) / 2.0
                            shoulder_y = (kp[5][1] + kp[6][1]) / 2.0
                            hip_x = (kp[11][0] + kp[12][0]) / 2.0
                            hip_y = (kp[11][1] + kp[12][1]) / 2.0
                            
                            if not (shoulder_x == 0 or hip_x == 0):
                                dy = hip_y - shoulder_y
                                dx = hip_x - shoulder_x
                                body_angle = np.abs(np.degrees(np.arctan2(dy, dx)))
                                if body_angle < 40.0 or (w_box / h_box) > 1.25:
                                    is_physically_lying = True
                        except Exception:
                            pass
                            
                        # 跌倒防線 B：遮擋防禦
                        if normal_h_reference is not None:
                            if (h_box / normal_h_reference) < 0.70 and y2 > (img_h * 0.5):
                                is_occluded_fall = True
                                
                        # === 💥 核心修正：半夜離床虛擬圍籬的雙重防禦 ===
                        is_night_time = True  
                        # 1. 只有當這支鏡頭名稱裡面有 "Bed" 字眼時，才允許啟動床沿圍籬。
                        # 2. 如果人已經在影像中倒地躺下了，絕對不准觸發離床預警，必須交由下方的跌倒邏輯處理。
                        if (is_night_time and 
                            bed_box_xyxy is not None and 
                            "Bed" in camera_id and 
                            not is_physically_lying):
                            
                            bed_ymin, bed_ymax = bed_box_xyxy[1], bed_box_xyxy[3]
                            left_ankle_y = kp[15][1] * img_h
                            right_ankle_y = kp[16][1] * img_h
                            
                            bed_trigger_line = bed_ymin + (bed_ymax - bed_ymin) * 0.85
                            if (left_ankle_y > bed_trigger_line and left_ankle_y != 0) or (right_ankle_y > bed_trigger_line and right_ankle_y != 0):
                                is_leaving_bed = True
            except Exception:
                pass

        if not is_current_frame_valid and has_seen_person:
            current_pose_feat = last_pose_feat.copy()

        # === Step 3: 將特徵推入視窗並進行時序運算 ===
        frame_window.append(current_pose_feat)
        status_text = "Normal"
        color = (0, 255, 0) 
        act_confidence = 0.0
        draw_border = True   

        pred_class = 1  
        if len(frame_window) == 30:
            np_window = np.array(frame_window, dtype=np.float32)
            input_tensor = torch.from_numpy(np_window).unsqueeze(0).to(device)
            with torch.no_grad():
                outputs = transformer_model(input_tensor)
                prob = torch.softmax(outputs, dim=1)
                pred_class = torch.argmax(prob, dim=1).item()
                act_confidence = prob[0][pred_class].item()

        is_ai_thinking_fall = (pred_class == 0 and act_confidence > 0.35) if len(frame_window) == 30 else False
        
        # 💡 跌倒核心判定
        should_trigger_fall = False
        if has_seen_person:
            if is_physically_lying or is_occluded_fall:  
                if len(frame_window) < 30 or is_ai_thinking_fall or is_occluded_fall:
                    should_trigger_fall = True
            elif len(frame_window) == 30 and pred_class == 0 and act_confidence > 0.55:
                should_trigger_fall = True

        if should_trigger_fall:
            status_text = "FALL DETECTED!"
            color = (0, 0, 255) 
            ever_detected_fall = True # 💡 歷史鎖死
            
            if act_confidence == 0.0 and is_occluded_fall:
                occluded_frames_counter += 1  
                if occluded_frames_counter > 6:
                    act_confidence = 0.95  
                else:
                    act_confidence = 0.70  
            else:
                if act_confidence == 0.0:
                    act_confidence = 0.75
        
        # 💡 優先順序 2：若無跌倒，檢查是否觸發【半夜離床預警】
        elif is_leaving_bed and not ever_detected_fall:
            status_text = "BED EXIT PRE-ALERT"
            color = (0, 165, 255) # 🟠 橘色
            if occluded_frames_counter > 0: occluded_frames_counter -= 1
            
            if not bed_alert_triggered:
                bed_alert_triggered = True
                bed_payload = {
                    "alert_id": f"BED_{camera_id}_{int(time.time())}",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    "room_no": camera_id,        
                    "alert_type": "Bed_Exit_Pre_Alert", 
                    "vlm_summary": "【長照預警系統：半夜離床通知】邊緣圍籬感測到長輩雙腳已探出床沿，疑似正要起身離床。請值班護理人員提早前往協助，防範跌倒風險。",
                    "status": "UNREAD"
                }
                if producer is not None:
                    # 💡 離床預警也直接發往最終結果的 processed-reports 主通道
                    producer.send('processed-reports', value=bed_payload)
                    producer.flush()
                    print(f"🟠 [{camera_id}] 長輩半夜離床！已直接外發至終端通報微服務。")
        else:
            # 💡 解決人影瞬間消失造成的斷崖退色：只要歷史曾經觸發跌倒，直到影片結束前一律保持跌倒！
            if ever_detected_fall:
                status_text = "FALL DETECTED!"
                color = (0, 0, 255)
            else:
                if occluded_frames_counter > 0: occluded_frames_counter -= 1
                if len(frame_window) < 30:
                    status_text = "Buffering..."
                    color = (0, 255, 255) 
                    draw_border = False   
                else:
                    status_text = "Normal"
                    color = (0, 255, 0) 

        # === 跌倒警報 Kafka 雙軌分流發送 ===
        if status_text == "FALL DETECTED!" and not vlm_triggered:
            env_clues_str = ", ".join(detected_objects) if detected_objects else "No specific objects"
            alert_payload = {
                "alert_id": f"ALT_{camera_id}_{int(time.time())}",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                "room_no": camera_id,        
                "env_clues": env_clues_str,
                "confidence": f"{act_confidence*100:.1f}%" if act_confidence > 0 else "70.0%"
            }
            
            if producer is not None:
                # 💡 【完美導航修正】：只有不是遮擋的「高置信度清爽跌倒」才可以走快速道路
                if act_confidence > 0.90 and not is_occluded_fall:
                    vlm_triggered = True
                    alert_payload["alert_type"] = "Critical_Fast_Track"
                    alert_payload["vlm_summary"] = "【緊急通報】邊緣核心高置信度判定發生跌倒！請立刻前往救援。"
                    alert_payload["status"] = "UNREAD"
                    producer.send('processed-reports', value=alert_payload)
                    producer.flush()
                    vlm_report = "Fast-track Sent"
                
                # 💡 【核心強迫】：只要是「遮擋跌倒」，通通不准走快速道路，第一秒強制發給第一個 Kafka 召喚 VLM 審查！
                else:
                    vlm_triggered = True
                    alert_payload["alert_type"] = "Pending_VLM_Review"
                    snapshot_name = f"snapshot_{camera_id}.jpg"
                    cv2.imwrite(snapshot_name, frame)
                    with open(snapshot_name, "rb") as img_file:
                        img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                    alert_payload["image_base64"] = img_base64
                    
                    # 📢 灌入第一個 Kafka (Topic: nursing-home-alerts)
                    producer.send('nursing-home-alerts', value=alert_payload)
                    producer.flush()
                    vlm_report = "VLM Queued..."

        # === Step D: 多任務畫布渲染 ===
        annotated_frame = results_pose[0].plot(boxes=True, labels=True, conf=0.45) 
        if draw_border:
            cv2.rectangle(annotated_frame, (0, 0), (img_w, img_h), color, 12)
        
        cv2.putText(annotated_frame, status_text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)
        cv2.putText(annotated_frame, f"VLM Status: {vlm_report}", (40, img_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        
        if is_current_frame_valid:
            last_valid_annotated_frame = annotated_frame.copy()

        with frames_lock:
            output_frames[camera_id] = annotated_frame.copy()

        t_elapsed = time.time() - t_start
        t_sleep = frame_delay - t_elapsed
        if t_sleep > 0: time.sleep(t_sleep)

    cap.release()

# =========================================================================
# 🏢 主執行緒專職 GUI 與排列控制
# =========================================================================
if __name__ == "__main__":
    camera_channels = {
        "Room_301_Bed": "test_demo/test2.mp4",        
        "Room_302_Door": "test_demo/test3.mp4",       
    }
    
    print(f"🎬 全連鎖安養中心多鏡頭智能分流管線全面啟動，共計 {len(camera_channels)} 路鏡頭...")
    
    threads = []
    for cam_id, stream_src in camera_channels.items():
        t = threading.Thread(target=camera_worker, args=(cam_id, stream_src))
        t.daemon = True  
        threads.append(t)
        t.start()
        
    try:
        frame_interval = 1.0 / 30.0  
        window_positions = {}  
        
        while True:
            start_time = time.time()
            active_windows = False
            
            current_display_frames = {}
            with frames_lock:
                current_display_frames = output_frames.copy()
                
            for idx, (cam_id, img_to_show) in enumerate(current_display_frames.items()):
                if img_to_show is not None:
                    win_name = f"Fall Detection System - {cam_id}"
                    cv2.imshow(win_name, img_to_show)
                    
                    if win_name not in window_positions:
                        x_pos = 50 + (idx * 660)  
                        y_pos = 70
                        cv2.moveWindow(win_name, x_pos, y_pos)
                        window_positions[win_name] = (x_pos, y_pos)
                    active_windows = True
            
            if active_windows:
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("\n👋 收到使用者終止指令 'q'。")
                    break
            
            elapsed = time.time() - start_time  
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                time.sleep(0.001)
                
    except KeyboardInterrupt:
        print("\n👋 收到終止訊號，系統安全關閉。")
    finally:
        cv2.destroyAllWindows()
        if producer is not None:
            print("⏳ 正在安全關閉 Kafka Producer，推送剩餘緩衝數據...")
            producer.close()
            print("✅ 訊息傳輸完畢，Producer 已安全關閉。")
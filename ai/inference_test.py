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

from triton_pose_client import TritonPoseModel          # Triton 版 yolo_pose client（人體姿態）
from triton_detr_client import TritonDetrModel          # Triton 版 rt_detr client（環境物件偵測）
from triton_act_client import TritonActModel            # Triton 版 action_transformer client（時序跌倒分類）

from av_reader import open_source                        # AV1 影片解碼（PyAV），介面對齊 cv2.VideoCapture

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
# 🚦 C 組信心分流（Uncertainty Router 的極簡前身）
# =========================================================================
# ≥ FAST_TRACK_CONF = 高信心快速道（直入 processed-reports → 後端落 PostgreSQL，不經 VLM 二審）；
# < FAST_TRACK_CONF = 低信心走 nursing-home-alerts → vlm_worker 二審 → 回 processed-reports。
FAST_TRACK_CONF = 0.90  # 規格：AcT 信心 ≥0.9 直入 PG、<0.9 走 VLM 二審

# Kafka topic 名稱是不能動的契約邊界（後端/vlm_worker 共用），集中成常數避免各處手打拼錯。
TOPIC_PROCESSED_REPORTS = "processed-reports"   # 高信心快速道 + 二審完成 → 後端 consumer 寫 PG
TOPIC_NURSING_HOME_ALERTS = "nursing-home-alerts"  # 低信心 → VLM 二審佇列


def route_by_confidence(*, act_confidence, is_chair_slipped, is_occluded_fall,
                        event_label, numeric_id, video_source, detected_at,
                        snapshot_full_path, snapshot_name, final_score, yolo_thresh):
    """依 AcT 信心把單一跌倒/滑落事件路由到對應 Kafka topic，回傳 (topic, payload)。

    這是 C 組信心分流的乾淨抽離點（原本寫死在 camera_worker 裡的 if/else）：
      - 高信心（act_confidence >= FAST_TRACK_CONF 或明確 chair_slip）且非遮擋不確定
        → (processed-reports, 快速道 payload)：後端 consumer 直接落 PostgreSQL，不經 VLM。
      - 其餘（信心不足 / 遮擋難判）
        → (nursing-home-alerts, 待審 payload)：走 Kafka → vlm_worker 二審 → 回 processed-reports。

    兩個 payload 的欄位名與型別（device_id(int)/event_type/detected_at(ISO)/snapshot_path/
    vlm_summary/severity …）是後端契約，維持不動。第 2 層 LangGraph Uncertainty Router
    之後可直接 import 本函式接管路由決策，介面不變（VLMModel.infer 已隔離、與此對齊）。
    """
    is_fast_track = (act_confidence >= FAST_TRACK_CONF or is_chair_slipped) and not is_occluded_fall

    if is_fast_track:
        # 🟢 分流 A：快速道路（Critical_Fast_Track）——高信心/明確滑落，直入後端落庫。
        payload = {
            "device_id": numeric_id,
            "event_type": event_label,
            "clip_path": str(video_source),
            "detected_at": detected_at,
            "snapshot_path": snapshot_full_path,
            "image_filename": snapshot_name,
            "yolo_score": final_score,
            "yolo_threshold": yolo_thresh,
            "vlm_summary": "【緊急通報】邊緣端偵測到輪椅意外滑落/嚴重跌倒！請立刻前往救援。",
            "severity": "high",
        }
        return TOPIC_PROCESSED_REPORTS, payload

    # 🔵 分流 B：慢速道路（Pending_VLM_Review）——信心不足/遮擋難判，送 VLM 二審。
    payload = {
        "device_id": numeric_id,
        "event_type": event_label,
        "clip_path": str(video_source),
        "detected_at": detected_at,
        "snapshot_path": snapshot_full_path,
        "image_filename": snapshot_name,
        "yolo_score": final_score,
        "yolo_threshold": yolo_thresh,
        "vlm_summary": "【AI 信心度不足】已觸發大模型二審，正在分析影像特徵並生成詳細報告...",
        "severity": "medium",
    }
    return TOPIC_NURSING_HOME_ALERTS, payload

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
print("📦 正在載入 Triton 三顆模型（yolo_pose / rt_detr / action_transformer）...")
# 依最新系統流程：三顆模型都上 Triton。pose 打 yolo_pose、環境物件偵測打 rt_detr、
# 時序跌倒分類（AcT）打 action_transformer。三個 client 呼叫介面都貼近原本本地呼叫：
#   - TritonPoseModel / TritonDetrModel 回標準 ultralytics Results，下游 .keypoints/.plot()
#     與 .boxes/.names 完全不用改；
#   - TritonActModel 回原始 logits (1,2) ndarray，下游 torch.softmax/argmax 幾乎不用改。
TRITON_POSE_URL = os.environ.get("TRITON_POSE_URL", "http://127.0.0.1:8000/yolo_pose")
TRITON_DETR_URL = os.environ.get("TRITON_DETR_URL", "http://127.0.0.1:8000/rt_detr")
TRITON_ACT_URL = os.environ.get("TRITON_ACT_URL", "http://127.0.0.1:8000/action_transformer")
yolo_pose_model = TritonPoseModel(TRITON_POSE_URL)   # 人體姿態打 Triton yolo_pose
yolo_env_model = TritonDetrModel(TRITON_DETR_URL)    # 環境物件偵測打 Triton rt_detr

# AcT 改打 Triton action_transformer。保留原本的降級語意：若 Triton 的 AcT 不可用
# （client 建構失敗等），transformer_model 設 None，下游 len(frame_window)==30 的分支
# 會退回「is_physically_lying 幾何模擬」機制，不讓整支 crash。實際的 Triton 連線是
# thread-local 延遲建立（見 TritonActModel），這裡只是建 wrapper 物件、不會真的連線。
try:
    transformer_model = TritonActModel(TRITON_ACT_URL)
    print("🔥 Triton 三顆 client 就緒，多任務平行化管線就緒！")
except Exception as e:
    print(f"⚠️ 建立 TritonActModel 失敗（{e}），將使用模擬機制運行時序推理。")
    transformer_model = None

output_frames = {}
frames_lock = threading.Lock()

# =========================================================================
# 📹 核心：多鏡頭平行巡邏的 Edge Worker
# =========================================================================
def camera_worker(camera_id, video_source):
    global producer, device, yolo_pose_model, yolo_env_model, transformer_model, output_frames, frames_lock
    
    print(f"🚀 鏡頭頻道 [{camera_id}] 啟動拉流：{video_source}")
    # 影片檔（AV1）走 PyAV 解碼、webcam index 走 cv2；介面與 cv2.VideoCapture 相同。
    cap = open_source(video_source)
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
    triton_down_warned = False  # Triton 斷線降級提示只印一次，避免逐幀刷屏

    # ── FPS 量測（只印 log，不影響推論邏輯）──────────────────────────────
    # 每 FPS_LOG_EVERY 個「實際處理的幀」印一次區間實測 FPS。量的是「經過 Triton 三顆
    # 推論＋六大防線的幀」的處理速率（processed FPS），對照 Mac 端數字用。
    # FPS_NO_THROTTLE=1 時略過迴圈尾端的 time.sleep(frame_delay) 節流，量「純 GPU 吞吐上限」
    #（不被 source fps 綁住）；不設則保留原節流、量「貼齊 source fps 的穩態處理速率」。
    _fps_no_throttle = bool(os.environ.get("FPS_NO_THROTTLE"))
    _fps_log_every = int(os.environ.get("FPS_LOG_EVERY", "60"))
    # 提速：NO_RENDER=1 時跳過 Step D 純畫圖渲染（.plot()/mask 疊圖/putText/copy），
    # 這些只為 GUI 顯示，HEADLESS 壓測根本不看畫面卻每幀白燒 CPU。快照存檔仍保留（事件證據）。
    _no_render = bool(os.environ.get("NO_RENDER"))
    _fps_t0 = time.time()
    _fps_n = 0            # 本區間已處理幀數
    _fps_proc_total = 0   # 累計已處理幀數
    _fps_run_t0 = time.time()
    
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

        # ── FPS 量測：只數「真的進到推論」的幀（跳過的幀不算），每區間印一次 ──
        _fps_n += 1
        _fps_proc_total += 1
        if _fps_n >= _fps_log_every:
            _now = time.time()
            _dt = _now - _fps_t0
            _inst = _fps_n / _dt if _dt > 0 else 0.0
            _avg = _fps_proc_total / (_now - _fps_run_t0) if (_now - _fps_run_t0) > 0 else 0.0
            _mode = "GPU吞吐(無節流)" if _fps_no_throttle else "穩態(含節流)"
            print(f"📊 [FPS/{_mode}] [{camera_id}] 區間 {_inst:5.1f} fps｜累計均 {_avg:5.1f} fps"
                  f"（已處理 {_fps_proc_total} 幀）")
            _fps_t0 = _now
            _fps_n = 0

        # 核心推理：同時運行 Pose 與 Seg 模型
        # Triton 斷線降級：pose/detr 的連線是 thread-local 首次呼叫才建立，Triton 掛掉時會在
        # 此拋錯。用 try/except 接住讓「該相機 worker 續跑」（頂多該幀跳過），不讓未捕捉例外
        # 殺掉整條 worker 執行緒——保留 Albert 原設計的容錯：某路 Triton 抖動不影響其他相機。
        try:
            results_pose = yolo_pose_model(frame, verbose=False, conf=0.45)
        except Exception as e:
            if not triton_down_warned:
                print(f"⚠️ [{camera_id}] Triton pose 推論失敗（降級：略過此幀，持續重試）：{e}")
                triton_down_warned = True
            t_sleep = frame_delay - (time.time() - t_start)
            if t_sleep > 0: time.sleep(t_sleep)
            continue
        try:
            results_env = yolo_env_model(frame, verbose=False, conf=0.35)  # rt_detr 環境物件偵測
        except Exception as e:
            if not triton_down_warned:
                print(f"⚠️ [{camera_id}] Triton rt_detr 推論失敗（降級：本幀不做環境物件疊圖）：{e}")
                triton_down_warned = True
            results_env = None  # 下游 `if results_env and ...` guard 可容忍 None
        
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
        is_whitespace = False  
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
        
        act_triton_ok = False
        if len(frame_window) == 30 and transformer_model is not None:
            np_window = np.array(frame_window, dtype=np.float32)
            # TritonActModel 回原始 logits (1,2) ndarray；softmax/argmax 沿用原本邏輯。
            # Triton 斷線降級：AcT 連線同為 thread-local 首次呼叫才建立，Triton 掛掉時這裡拋錯。
            # 接住後退回下面的「is_physically_lying 幾何模擬」分支，不讓整條 worker 崩。
            try:
                logits = transformer_model(np_window)
                outputs = torch.from_numpy(np.asarray(logits, dtype=np.float32))
                prob = torch.softmax(outputs, dim=1)
                pred_class = torch.argmax(prob, dim=1).item()
                act_confidence = prob[0][pred_class].item()
                act_triton_ok = True
            except Exception as e:
                if not triton_down_warned:
                    print(f"⚠️ [{camera_id}] Triton AcT 推論失敗（降級：退回幾何模擬判斷）：{e}")
                    triton_down_warned = True
        if len(frame_window) == 30 and not act_triton_ok:
            # transformer_model 為 None（建構期就沒 AcT）或 Triton 呼叫失敗，皆走幾何模擬。
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
        # ⚡ ⚡ ⚡ 業界商用規格修改：動態不重複相片命名與傳遞 ⚡ ⚡ ⚡
        # =========================================================================
        if (should_trigger_fall or is_chair_slipped) and not vlm_triggered:
            # 🧠 1. 解析並對齊 device_id 為 int
            try:
                numeric_id = int(''.join(filter(str.isdigit, camera_id)))
            except ValueError:
                numeric_id = 1
                
            # 🧠 2. 對齊事件型態字串
            event_label = "chair_slip" if is_chair_slipped else "fall"
            
            # 🧠 3. 基礎 YOLO 推理數據規格化
            final_score = float(act_confidence) if act_confidence > 0 else 0.70
            yolo_thresh = 0.45 if event_label == "fall" else 0.35

            # 🧠 4. 【生產品級核心】動態不重複檔名機制 (帶精確時間戳)
            current_time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            snapshot_name = f"snapshot_{camera_id}_{current_time_str}.jpg"  # 不重複檔名
            snapshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
            os.makedirs(snapshot_dir, exist_ok=True)
            snapshot_full_path = os.path.join(snapshot_dir, snapshot_name)
            cv2.imwrite(snapshot_full_path, frame)  # 實體不重複存檔留存

            if producer is not None:
                vlm_triggered = True
                # 🚦 信心分流抽成 route_by_confidence()：由它決定送哪個 topic、組哪個 payload。
                # 這裡只負責算好參數、把回傳的 (topic, payload) 送出，路由決策可被 LangGraph 接管。
                topic, payload = route_by_confidence(
                    act_confidence=act_confidence,
                    is_chair_slipped=is_chair_slipped,
                    is_occluded_fall=is_occluded_fall,
                    event_label=event_label,
                    numeric_id=numeric_id,
                    video_source=video_source,
                    detected_at=datetime.now().isoformat(),  # 符合後端解析的 ISO 時間字串
                    snapshot_full_path=snapshot_full_path,
                    snapshot_name=snapshot_name,
                    final_score=final_score,
                    yolo_thresh=yolo_thresh,
                )
                producer.send(topic, value=payload)
                producer.flush()
                # 畫面上的 VLM 狀態依落點提示：快速道 vs 送二審佇列。
                vlm_report = "Fast-track Sent" if topic == TOPIC_PROCESSED_REPORTS else "VLM Queued..."

        # === Step D: 畫布渲染（✅ 自動半透明疊加不規則物件輪廓） ===
        # NO_RENDER=1（HEADLESS 壓測）：整段純畫圖只為 GUI 顯示，跳過以省 CPU；偵測/外發/快照不受影響。
        if not _no_render:
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

        # FPS_NO_THROTTLE=1：量純 GPU 吞吐上限時，略過貼齊 source fps 的節流睡眠。
        if not _fps_no_throttle:
            t_elapsed = time.time() - t_start
            t_sleep = frame_delay - t_elapsed
            if t_sleep > 0: time.sleep(t_sleep)

    cap.release()

# =========================================================================
# 🏢 主執行緒專職 GUI 與排列控制
# =========================================================================
if __name__ == "__main__":
    # 💡 業界測試多路併發：可直接在此擴充相機與不同的測試影片
    # 測試影片放在 ai/test_demo/，以 __file__ 為基準解析絕對路徑，不受從哪個目錄啟動影響。
    _AI_DIR = os.path.dirname(os.path.abspath(__file__))
    camera_channels = {
        "Room_301_Bed": os.path.join(_AI_DIR, "test_demo", "test1.mp4"),
        "Room_302_Bed": os.path.join(_AI_DIR, "test_demo", "test2.mp4"),
        "Room_303_Bed": os.path.join(_AI_DIR, "test_demo", "test3.mp4"),
    }
    # 單源量測開關（比照其他開關：未設 = 原三路行為，不留死改動）：
    # SINGLE_SOURCE=<檔案路徑或 rtsp URL> 時，改成「只掛一路」指向該來源，量單路乾淨 FPS
    #（避免三/四路併發共享 GPU 稀釋數字）。相機名固定 Room_301_Bed（device_id=301，已在後端註冊）。
    # 例：SINGLE_SOURCE=ai/test_demo/test4.mp4 FPS_NO_THROTTLE=1 python ai/inference_test.py
    _SINGLE = os.environ.get("SINGLE_SOURCE")
    if _SINGLE:
        if "://" in _SINGLE or os.path.isabs(_SINGLE):
            _src = _SINGLE                                   # URL 或絕對路徑：原樣用
        else:
            # 相對路徑：以「repo 根」為基準（_AI_DIR 是 ai/，其上一層是 repo 根）。
            _src = os.path.normpath(os.path.join(_AI_DIR, "..", _SINGLE))
        camera_channels = {"Room_301_Bed": _src}
        print(f"🎯 [單源量測] SINGLE_SOURCE → 只掛一路：Room_301_Bed = {_src}")

    # 即時串流（RTSP）測試開關：設了 RTSP_TEST_URL 就多掛一路即時流（open_source 走 PyAV 拉流），
    # mp4 三路照跑不受影響。例：RTSP_TEST_URL=rtsp://127.0.0.1:8554/test python ai/inference_test.py
    _RTSP_TEST = os.environ.get("RTSP_TEST_URL")
    if _RTSP_TEST:
        camera_channels["RTSP_Live_Test"] = _RTSP_TEST
        print(f"📡 已掛入 RTSP 即時流測試頻道：{_RTSP_TEST}")

    # 壓測開關（比照 RTSP_TEST_URL：未設環境變數 = 位元級原行為，不留死改動）：
    # STRESS_CAM_COUNT=N 時，把現有 test1/2/3.mp4 循環重複掛成 N 個唯一房間頻道
    # （Room_301..30N，src 用 test1/2/3 輪替）。壓測看的是「N 路併發吞吐」，不是內容，
    # 所以重複掛同幾支影片即可。例：STRESS_CAM_COUNT=5 python ai/inference_test.py
    _STRESS_CAM_COUNT = os.environ.get("STRESS_CAM_COUNT")
    if _STRESS_CAM_COUNT:
        _n = int(_STRESS_CAM_COUNT)
        _pool = [os.path.join(_AI_DIR, "test_demo", f"test{i}.mp4") for i in (1, 2, 3)]
        camera_channels = {
            f"Room_{301 + i}_Bed": _pool[i % len(_pool)] for i in range(_n)
        }
        print(f"🔥 [壓測] STRESS_CAM_COUNT={_n} → 掛 {_n} 路併發頻道：{list(camera_channels.keys())}")
    print(f"🎬 全連鎖安養中心多鏡頭多模態智能管線全面啟動（多路不重複留存模式啟用）...")
    
    threads = []
    for cam_id, stream_src in camera_channels.items():
        t = threading.Thread(target=camera_worker, args=(cam_id, stream_src))
        t.daemon = True; threads.append(t); t.start()

    # Headless 壓測開關（未設 = 原本 GUI 行為，不留死改動）：HEADLESS=1 時主執行緒不畫
    # imshow（避免 GUI 拖慢壓測數字、且 WSL2 無 X server 會卡），改成純等 worker 跑完影片。
    # worker 本體完全不動，只是主執行緒不進顯示迴圈。
    if os.environ.get("HEADLESS"):
        print("🖥️  [壓測] HEADLESS=1 → 不開 GUI 視窗，主執行緒等待所有 worker 跑完影片流...")
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            pass
        finally:
            if producer is not None: producer.close()
        raise SystemExit(0)

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
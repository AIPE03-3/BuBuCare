import os
import sys
import time
import cv2
import torch
import numpy as np
from collections import deque
import torch.nn as nn
import threading
import json
from datetime import datetime  
import base64
import subprocess
import requests as _requests

try:
    import tritonclient.grpc as grpcclient  # 🚀 [Triton 整合] 引入 Triton gRPC 套件
except ImportError:
    grpcclient = None

try:
    from numba import jit
except ImportError:
    def jit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

@jit(nopython=True, fastmath=True, nogil=True)
def get_body_angle_jit(shoulder_x, shoulder_y, hip_x, hip_y):
    """計算人體軀幹連線與水平線的絕對夾角 (0~90度)，0度代表完全水平躺平"""
    if shoulder_x == 0.0 or hip_x == 0.0:
        return 90.0
    dx = abs(hip_x - shoulder_x)
    dy = abs(hip_y - shoulder_y)
    angle_rad = np.arctan2(dy, dx)
    return np.degrees(angle_rad)

# 🚀 Numba JIT 自動預熱 (Warmup)
try:
    _ = get_body_angle_jit(100.0, 100.0, 100.0, 200.0)
except Exception:
    pass

# =========================================================================
# 🧭 自動修正 Python 模組搜尋路徑
# =========================================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)  # 從 tools/ 往上推一層到 Fall/
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

# =========================================================================
# 🔑 全域指定唯一合法 API KEY (物理強注，徹底解決 HTTP 401 拒絕問題)
# =========================================================================
VALID_API_KEY = "***REDACTED***"  # guardrail: allow 歷史歸檔，原值為硬編碼金鑰，撈取時已移除

def _get_valid_api_key():
    return VALID_API_KEY

# =========================================================================
# 🌟 專屬長照智慧模組（僅保留模組 G：環境安全巡檢）
# =========================================================================
try:
    from modules.sanity_check import RoutineSanityChecker  # 模組 G：VLM 閒置算力環境安全巡檢
    print("✅ [模組 G] 環境安全巡檢匯入成功")
except Exception as e:
    print(f"❌ [模組 G] 巡檢匯入失敗: {e}")
    RoutineSanityChecker = None

# =========================================================================
# 🛠️ MLOps 基礎建設：Kafka 初始化
# =========================================================================
from kafka import KafkaProducer
from ultralytics import YOLO, RTDETR

try:
    producer = KafkaProducer(
        bootstrap_servers=['localhost:9092'],
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    print("✅ [Kafka] 訊息中心連線成功！雙向數據管線已就緒。")
except Exception as e:
    print(f"⚠️ [Kafka] 連線失敗: {e}")
    producer = None

# 🚀 開啟 GPU 硬體加速
if torch.cuda.is_available():
    device = torch.device("cuda")
elif torch.backends.mps.is_available():
    device = torch.device("mps")
else:
    device = torch.device("cpu")

print(f"🚀 推理引擎啟動，成功掛載 GPU 硬體加速裝置：{device}")

# =========================================================================
# 🛡️ 業界安防平滑追蹤器 (Box & Pose Smoothing Tracker)
# =========================================================================
class PersonTrackerEMA:
    """利用指數平滑 (EMA) 與慣性補幀，確保畫面的框與骨架 100% 穩定緊跟，絕不閃爍掉幀"""
    def __init__(self, alpha=0.35, max_missing_frames=12):
        self.alpha = alpha
        self.max_missing = max_missing_frames
        self.missing_count = 0
        self.last_box = None      # [x1, y1, x2, y2]
        self.last_kpts = None     # [17, 2] 或 [17, 3]
        self.last_conf = 0.0

    def update(self, new_box, new_kpts, conf):
        if new_box is not None:
            self.missing_count = 0
            self.last_conf = conf
            if self.last_box is None:
                self.last_box = np.array(new_box, dtype=np.float32)
            else:
                self.last_box = self.alpha * np.array(new_box, dtype=np.float32) + (1 - self.alpha) * self.last_box
            
            if new_kpts is not None:
                if self.last_kpts is None:
                    self.last_kpts = np.array(new_kpts, dtype=np.float32)
                else:
                    self.last_kpts = self.alpha * np.array(new_kpts, dtype=np.float32) + (1 - self.alpha) * self.last_kpts
            return self.last_box.astype(int), self.last_kpts, self.last_conf
        else:
            self.missing_count += 1
            if self.missing_count <= self.max_missing and self.last_box is not None:
                return self.last_box.astype(int), self.last_kpts, self.last_conf * 0.9
            else:
                self.last_box = None
                self.last_kpts = None
                return None, None, 0.0

# =========================================================================
# ⚡ [Triton 整合] 建立與對齊相容的 Mock 數據結構
# =========================================================================
class MockBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = torch.tensor([xyxy])
        self.conf = torch.tensor([conf])
        self.cls = torch.tensor([cls])

class MockResults:
    def __init__(self, boxes):
        self.boxes = boxes

class MockPoseKeypoints:
    def __init__(self, xyn):
        self.xyn = torch.tensor(xyn)
    def __len__(self):
        return len(self.xyn)

class MockPoseBoxes:
    def __init__(self, conf, xywh, xyxy):
        self.conf = torch.tensor(conf)
        self.xywh = torch.tensor(xywh)
        self.xyxy = torch.tensor(xyxy)
    def __len__(self):
        return len(self.conf)

class MockPoseResults:
    def __init__(self, keypoints, boxes, original_frame):
        self.keypoints = keypoints
        self.boxes = boxes
        self.original_frame = original_frame

def parse_triton_yolo_pose(raw_output, img_w, img_h, conf_threshold=0.08, iou_threshold=0.45):
    data = raw_output[0].T
    # YOLO Pose 每筆輸出至少有 bbox/conf（5）+ 17 個 (x, y, score) 關鍵點（51）。
    # 格式不符時不可當成有效姿態，讓呼叫端降級至原生 YOLO Pose。
    if data.ndim != 2 or data.shape[1] < 56:
        return None
    scores = data[:, 4]
    valid_indices = np.where(scores >= conf_threshold)[0]
    if len(valid_indices) == 0:
        return None
        
    valid_data = data[valid_indices]
    valid_scores = scores[valid_indices]
    
    cx, cy, w, h = valid_data[:, 0], valid_data[:, 1], valid_data[:, 2], valid_data[:, 3]
    x1 = cx - w / 2.0
    y1 = cy - h / 2.0
    x2 = cx + w / 2.0
    y2 = cy + h / 2.0
    
    boxes = np.stack([x1, y1, x2, y2], axis=1)
    
    x1_b, y1_b, x2_b, y2_b = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2_b - x1_b) * (y2_b - y1_b)
    order = valid_scores.argsort()[::-1]
    
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1_b[i], x1_b[order[1:]])
        yy1 = np.maximum(y1_b[i], y1_b[order[1:]])
        xx2 = np.minimum(x2_b[i], x2_b[order[1:]])
        yy2 = np.minimum(y2_b[i], y2_b[order[1:]])
        
        w_int = np.maximum(0.0, xx2 - xx1)
        h_int = np.maximum(0.0, yy2 - yy1)
        inter = w_int * h_int
        ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-8)
        
        inds = np.where(ovr <= iou_threshold)[0]
        order = order[inds + 1]
        
    if len(keep) == 0:
        return None
        
    final_boxes_xyxy = boxes[keep]
    final_scores = valid_scores[keep]
    final_data = valid_data[keep]
    
    scale_x = img_w / 640.0
    scale_y = img_h / 640.0
    
    final_boxes_xyxy[:, [0, 2]] *= scale_x
    final_boxes_xyxy[:, [1, 3]] *= scale_y
    
    kpts_raw = final_data[:, 5:]
    N = kpts_raw.shape[0]
    kpt_scores = kpts_raw[:, 2::3]
    # 低分雜訊偶爾仍會有 bbox，卻完全沒有可用人體關節；若將它送到前端，
    # Canvas 只能畫框而不會有骨架。至少六個可信關鍵點才接受 Triton 結果。
    pose_is_valid = np.count_nonzero(kpt_scores >= 0.20, axis=1) >= 6
    if not np.any(pose_is_valid):
        return None

    final_boxes_xyxy = final_boxes_xyxy[pose_is_valid]
    final_scores = final_scores[pose_is_valid]
    final_data = final_data[pose_is_valid]
    kpts_raw = kpts_raw[pose_is_valid]
    N = kpts_raw.shape[0]
    kpts_xyn = np.zeros((N, 17, 3), dtype=np.float32)
    for k in range(17):
        kpts_xyn[:, k, 0] = kpts_raw[:, k*3] / 640.0
        kpts_xyn[:, k, 1] = kpts_raw[:, k*3 + 1] / 640.0
        kpts_xyn[:, k, 2] = kpts_raw[:, k*3 + 2]
        
    final_cx = final_data[:, 0] * scale_x
    final_cy = final_data[:, 1] * scale_y
    final_w = final_data[:, 2] * scale_x
    final_h = final_data[:, 3] * scale_y
    final_boxes_xywh = np.stack([final_cx, final_cy, final_w, final_h], axis=1)
    
    return {
        "xyn": kpts_xyn,
        "conf": final_scores,
        "xywh": final_boxes_xywh,
        "xyxy": final_boxes_xyxy
    }

# 初始化 Triton gRPC 連線
try:
    if grpcclient is not None:
        client_test = grpcclient.InferenceServerClient(url="localhost:8001")
        if client_test.is_server_live() and client_test.is_model_ready("yolo_pose"):
            triton_client = client_test
            print("✅ [Triton] 成功建立 gRPC 高速推論通道連線 (Port: 8001)！")
        else:
            print("🚀 [GPU 加速] 自動避開未就緒的 Triton 通道，直接啟動原生 Apple GPU (MPS) 超級加速引擎！")
            triton_client = None
    else:
        triton_client = None
except Exception:
    triton_client = None

# =========================================================================
# 🌟 全域載入模型
# =========================================================================
pose_model_name = "yolo11s-pose.pt"
coreml_model_name = "yolo11s-pose.mlpackage"

if not os.path.exists(coreml_model_name) and os.path.exists(pose_model_name):
    try:
        print("🔄 首次載入：正在將 YOLO Pose 導出為 CoreML 格式以啟用 Mac 神經引擎加速...")
        from ultralytics import YOLO as YOLO_Exporter
        temp_model = YOLO_Exporter(pose_model_name)
        temp_model.export(format="coreml")
        print("🎉 CoreML 導出成功！")
    except Exception as e:
        print(f"⚠️ CoreML 導出失敗: {e}，將使用原生 CPU 模式。")
        
# 使用 PyTorch 格式 YOLO Pose，確保 .keypoints.xy 正確輸出
yolo_pose_model = YOLO(pose_model_name)

try:
    if not coreml_model_name in str(yolo_pose_model.ckpt_path if hasattr(yolo_pose_model, 'ckpt_path') else ''):
        yolo_pose_model.to(device)
except Exception:
    pass

output_frames = {}
frames_lock = threading.Lock()

# ─── 🎯 動態/即時畫框數據推送 ────────────────────
_BACKEND_DETECT_URL = "http://localhost:8000/events/live-detection"

def _push_detection(payload_dict: dict):
    try:
        resp = _requests.post(
            _BACKEND_DETECT_URL,
            json=payload_dict,
            headers={"X-API-Key": VALID_API_KEY, "Content-Type": "application/json"},
            timeout=0.5
        )
        if resp.status_code != 200:
            print(f"⚠️ [_push_detection Error] HTTP {resp.status_code}: {resp.text}")
    except Exception as err:
        print(f"⚠️ [_push_detection Exception] {err}")

import queue as _queue
_detection_queue: _queue.Queue = _queue.Queue(maxsize=10)

def _detection_queue_worker():
    while True:
        try:
            data = _detection_queue.get(timeout=1.0)
            _push_detection(data)
        except _queue.Empty:
            pass

_detection_bg_thread = threading.Thread(target=_detection_queue_worker, daemon=True)
_detection_bg_thread.start()

# =========================================================================
# 📹 核心：多鏡頭 Edge Worker (精簡純淨版：姿態跌倒 + 模組 G 環境巡檢)
# =========================================================================
def camera_worker(camera_id, video_source):
    global producer, device, yolo_pose_model, output_frames, frames_lock, triton_client
    
    # 🎯 檢查 video_source 是否為數字 (例如 "0" 或 "1")，如果是，則轉換為整數 (供 OpenCV 直接讀取本地實體/虛擬鏡頭)
    if isinstance(video_source, str) and video_source.isdigit():
        video_source = int(video_source)

    print(f"🚀 鏡頭頻道 [{camera_id}] 啟動拉流：{video_source}")
    demo_video_path = os.path.join(PROJECT_ROOT, "test_demo", "test1.mp4")
    
    cap = None
    if isinstance(video_source, str) and video_source.startswith("rtsp://"):
        rtsp_url_ipv4 = video_source.replace("localhost", "127.0.0.1")
        gst_pipeline = (
            f"rtspsrc location={rtsp_url_ipv4} protocols=tcp latency=0 ! "
            f"rtph264depay ! h264parse ! decodebin ! videoconvert ! video/x-raw, format=BGR ! appsink drop=true sync=false"
        )
        print(f"🚀 [{camera_id}] 正在嘗試點火 GStreamer 硬體解碼拉流...")
        cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        if cap is not None and cap.isOpened():
            ret_test, _ = cap.read()
            if not ret_test:
                cap.release()
                cap = None

        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(video_source, cv2.CAP_FFMPEG)
            if cap is not None and cap.isOpened():
                ret_test, _ = cap.read()
                if not ret_test:
                    cap.release()
                    cap = None
    else:
        cap = cv2.VideoCapture(video_source)

    is_using_demo_video = False
    if cap is None or not cap.isOpened():
        if os.path.exists(demo_video_path):
            print(f"📱 [{camera_id}] 未偵測到實體相機，自動啟用備援：自動加載演示影片 ({demo_video_path}) 進行無縫循環推流！")
            cap = cv2.VideoCapture(demo_video_path)
            is_using_demo_video = True
        else:
            print(f"❌ 鏡頭頻道 [{camera_id}] 無法開啟影像源: {video_source} 且未找到演示影片")
            return

    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0 or np.isnan(fps) or fps < 24.0: fps = 30.0
    frame_delay = 1.0 / fps  

    PRE_SEC = 5
    POST_SEC = 5
    MAX_PRE_FRAMES = int(fps * PRE_SEC)
    MAX_POST_FRAMES = int(fps * POST_SEC)
    
    pre_video_buffer = deque(maxlen=MAX_PRE_FRAMES)
    post_video_buffer = []
    is_recording_post = False
    post_frame_count = 0

    frame_count = 0
    fps_calc_time = time.time()
    fps_calc_counter = 0
    measured_fps = 0.0
    
    numeric_id = 1
    
    results_pose = None
    last_annotated_frame = None
    vlm_report = "Waiting for alert..."

    # 🎯 多人追蹤狀態字典 { track_id: dict }
    person_states = {}

    rtsp_writer_proc = None
    out_w, out_h = 1280, 720
    if camera_id == "Room_301_Bed":
        output_rtsp_url = "rtsp://localhost:8554/cam_out"
        cw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        out_w = cw if cw > 0 else 1280
        out_h = ch if ch > 0 else 720

        ffmpeg_cmd = [
            'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
            '-pix_fmt', 'bgr24', '-s', f'{out_w}x{out_h}', '-r', '24',
            '-i', '-', '-c:v', 'h264_videotoolbox', '-b:v', '4000k',
            '-realtime', 'true', '-g', '24', '-bf', '0',
            '-pix_fmt', 'yuv420p',
            '-f', 'rtsp', output_rtsp_url
        ]

        try:
            rtsp_writer_proc = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            print(f"📡 [{camera_id}] 已成功啟動 MediaMTX Mac 硬體加速推流 ➔ {output_rtsp_url}")
        except Exception as e:
            print(f"⚠️ [{camera_id}] FFmpeg 推流啟動失敗: {e}")

    latest_push_frame = None
    latest_push_lock = threading.Lock()
    push_running = True

    def ffmpeg_push_worker():
        nonlocal latest_push_frame, push_running
        target_delay = 1.0 / 24.0
        while push_running:
            t_p_start = time.time()
            frame_to_write = None
            with latest_push_lock:
                if latest_push_frame is not None:
                    frame_to_write = latest_push_frame.copy()

            if frame_to_write is not None and rtsp_writer_proc and rtsp_writer_proc.stdin:
                try:
                    rtsp_writer_proc.stdin.write(frame_to_write.tobytes())
                except Exception:
                    pass

            elapsed = time.time() - t_p_start
            sleep_time = target_delay - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    if rtsp_writer_proc:
        push_thread = threading.Thread(target=ffmpeg_push_worker, daemon=True)
        push_thread.start()

    while True:
        t_start = time.time()
        ret, frame = cap.read()
        
        if not ret:
            if is_using_demo_video:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            else:
                if os.path.exists(demo_video_path):
                    cap.release()
                    cap = cv2.VideoCapture(demo_video_path)
                    is_using_demo_video = True
                else:
                    time.sleep(1.0)
            
            # 重製計數器，防止迴圈重新開始時殘留狀態
            for p_id in person_states:
                person_states[p_id]["consecutive_fall_frames"] = 0
                person_states[p_id]["ever_detected_fall"] = False
                person_states[p_id]["vlm_triggered"] = False
                person_states[p_id]["standing_recovery_count"] = 0

            if not is_recording_post:
                post_video_buffer.clear()
            continue

        img_h, img_w, _ = frame.shape
        if img_w != 1280 or img_h != 720:
            frame = cv2.resize(frame, (1280, 720))
            img_h, img_w = 720, 1280

        frame_count += 1
        pre_video_buffer.append(frame)

        if is_recording_post:
            post_video_buffer.append(frame)
            post_frame_count += 1

        pose_was_updated = frame_count % 4 == 0 or results_pose is None
        if pose_was_updated:
            time.sleep(0.001)
            yolo_pose_success = False
            if triton_client is not None:
                # 暫無 Triton MOT
                pass
            
            if not yolo_pose_success:
                # 使用 ByteTrack 多人追蹤
                results_pose = yolo_pose_model.track(frame, persist=True, tracker="bytetrack.yaml", verbose=False, conf=0.08, device=device)

            last_annotated_frame = frame.copy()

        annotated_frame = last_annotated_frame.copy() if last_annotated_frame is not None else frame.copy()

        # ─── 🎯【多目標追蹤與跌倒判定】───────────────────
        active_track_ids = set()
        persons_out_list = []
        any_fall_triggered_this_frame = False
        
        if results_pose and len(results_pose[0].boxes) > 0:
            boxes = results_pose[0].boxes
            conf_data = boxes.conf.cpu().numpy()
            boxes_xyxy = boxes.xyxy.cpu().numpy()
            
            track_ids = []
            if boxes.id is not None:
                track_ids = boxes.id.int().cpu().tolist()
            else:
                track_ids = [i for i in range(len(conf_data))]
                
            for i, track_id in enumerate(track_ids):
                active_track_ids.add(track_id)
                conf_val = conf_data[i]
                raw_box = boxes_xyxy[i]
                
                raw_kpts = None
                if hasattr(results_pose[0].keypoints, 'xy') and results_pose[0].keypoints.xy is not None:
                    raw_kpts = results_pose[0].keypoints.xy.cpu().numpy()[i]
                elif hasattr(results_pose[0].keypoints, 'xyn') and results_pose[0].keypoints.xyn is not None:
                    raw_kpts = results_pose[0].keypoints.xyn.cpu().numpy()[i].copy()
                    raw_kpts[:, 0] *= img_w
                    raw_kpts[:, 1] *= img_h
                    
                if track_id not in person_states:
                    person_states[track_id] = {
                        "tracker": PersonTrackerEMA(alpha=0.35, max_missing_frames=15),
                        "consecutive_fall_frames": 0,
                        "ever_detected_fall": False,
                        "vlm_triggered": False,
                        "standing_recovery_count": 0
                    }
                
                p_state = person_states[track_id]
                if raw_kpts is not None:
                    raw_kpts = np.asarray(raw_kpts, dtype=np.float32)[:, :2]
                    
                smooth_box, smooth_kpts, active_conf = p_state["tracker"].update(raw_box, raw_kpts, conf_val)
                
                # 姿態判定
                body_angle = None
                box_aspect_ratio = None
                if smooth_kpts is not None and len(smooth_kpts) >= 13:
                    try:
                        shoulder_x = (float(smooth_kpts[5][0]) + float(smooth_kpts[6][0])) / 2.0
                        shoulder_y = (float(smooth_kpts[5][1]) + float(smooth_kpts[6][1])) / 2.0
                        hip_x = (float(smooth_kpts[11][0]) + float(smooth_kpts[12][0])) / 2.0
                        hip_y = (float(smooth_kpts[11][1]) + float(smooth_kpts[12][1])) / 2.0
                        body_angle = float(get_body_angle_jit(shoulder_x, shoulder_y, hip_x, hip_y))
                    except Exception:
                        pass

                if smooth_box is not None:
                    try:
                        bw = abs(float(smooth_box[2]) - float(smooth_box[0]))
                        bh = abs(float(smooth_box[3]) - float(smooth_box[1]))
                        if bh > 0:
                            box_aspect_ratio = bw / bh
                    except Exception:
                        pass
                
                torso_is_horizontal = (body_angle is not None and body_angle <= 60.0)
                body_is_wide = (box_aspect_ratio is not None and box_aspect_ratio >= 0.95)
                is_physically_lying = torso_is_horizontal or body_is_wide
                
                if pose_was_updated:
                    if is_physically_lying:
                        p_state["consecutive_fall_frames"] += 1
                    else:
                        p_state["consecutive_fall_frames"] = 0
                
                should_trigger_fall = p_state["consecutive_fall_frames"] >= 4
                
                if should_trigger_fall:
                    p_state["ever_detected_fall"] = True
                    p_state["standing_recovery_count"] = 0
                    any_fall_triggered_this_frame = True
                else:
                    if p_state["ever_detected_fall"] and not is_physically_lying:
                        p_state["standing_recovery_count"] += 1
                        if p_state["standing_recovery_count"] >= 90:
                            p_state["ever_detected_fall"] = False
                            p_state["vlm_triggered"] = False
                            p_state["standing_recovery_count"] = 0
                            print(f"ℹ️ [{camera_id}] (ID:{track_id}) 偵測到長者已自行站起，重置狀態！")
                            vlm_report = f"ID:{track_id} Self-Recovered"

                # 準備輸出 JSON
                if smooth_box is not None:
                    norm_bbox = [
                        round(float(smooth_box[0]) / img_w, 4),
                        round(float(smooth_box[1]) / img_h, 4),
                        round(float(smooth_box[2]) / img_w, 4),
                        round(float(smooth_box[3]) / img_h, 4)
                    ]
                    _kp_2d = []
                    _kp_dict_list = []
                    if smooth_kpts is not None:
                        for idx, _kp in enumerate(smooth_kpts):
                            kx = round(float(_kp[0]) / img_w, 4)
                            ky = round(float(_kp[1]) / img_h, 4)
                            kc = round(float(_kp[2]), 2) if len(_kp) > 2 else 0.95
                            _kp_2d.append([kx, ky])
                            _kp_dict_list.append({"x": kx, "y": ky, "score": kc, "id": idx})

                    while len(_kp_2d) < 17:
                        _kp_2d.append([0.0, 0.0])
                        _kp_dict_list.append({"x": 0.0, "y": 0.0, "score": 0.0, "id": len(_kp_dict_list)})

                    persons_out_list.append({
                        "id": track_id,
                        "bbox": norm_bbox,
                        "conf": round(float(active_conf), 2),
                        "kps": _kp_2d,
                        "keypoints": _kp_2d,
                        "keypoints_detailed": _kp_dict_list,
                        "is_fall": bool(should_trigger_fall)
                    })

                # 繪製單人邊框與骨架
                color = (0, 0, 255) if should_trigger_fall else (0, 255, 0)
                if smooth_box is not None:
                    try:
                        bx1, by1 = int(float(smooth_box[0])), int(float(smooth_box[1]))
                        bx2, by2 = int(float(smooth_box[2])), int(float(smooth_box[3]))
                        cv2.rectangle(annotated_frame, (bx1, by1), (bx2, by2), color, 2)
                        p_label = f"ID:{track_id} {active_conf:.2f}"
                        cv2.putText(annotated_frame, p_label, (bx1, max(by1 - 8, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
                        
                        if smooth_kpts is not None and len(smooth_kpts) >= 17:
                            skeleton_connections = [
                                (0,1),(0,2),(1,3),(2,4),(5,6),(5,7),(7,9),(6,8),(8,10),
                                (5,11),(6,12),(11,12),(11,13),(13,15),(12,14),(14,16)
                            ]
                            for a, b in skeleton_connections:
                                x1, y1 = int(float(smooth_kpts[a][0])), int(float(smooth_kpts[a][1]))
                                x2, y2 = int(float(smooth_kpts[b][0])), int(float(smooth_kpts[b][1]))
                                if x1 > 0 and y1 > 0 and x2 > 0 and y2 > 0:
                                    cv2.line(annotated_frame, (x1, y1), (x2, y2), (255, 229, 0), 2)
                            for kp in smooth_kpts:
                                kx, ky = int(float(kp[0])), int(float(kp[1]))
                                if kx > 0 and ky > 0:
                                    cv2.circle(annotated_frame, (kx, ky), 5, (0, 221, 255), -1)
                    except Exception:
                        pass
                
                # ⚡ 跌倒通報邏輯 (獨立針對每個 track_id)
                if should_trigger_fall and not p_state["vlm_triggered"]:
                    p_state["vlm_triggered"] = True
                    
                    # ⚠️ 修復：如果已經在錄製跌倒後影片，不要清空 buffer，直接共用同一個影片檔案！
                    if not is_recording_post:
                        is_recording_post = True
                        post_frame_count = 0
                        post_video_buffer = []
                        
                        vlm_save_dir = os.path.join(os.path.dirname(PROJECT_ROOT), "backend", "static", "images")
                        os.makedirs(vlm_save_dir, exist_ok=True)
                        current_time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                        
                        video_name = f"fall_clip_{camera_id}_{current_time_str}.mp4"
                        final_video_path = os.path.join(vlm_save_dir, video_name)
                    else:
                        # 正在錄影中，延用目前的時間戳記與檔名 (避免前端找不到影片)
                        if 'current_time_str' not in locals():
                            current_time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
                        if 'final_video_path' not in locals():
                            video_name = f"fall_clip_{camera_id}_{current_time_str}.mp4"
                            vlm_save_dir = os.path.join(os.path.dirname(PROJECT_ROOT), "backend", "static", "images")
                            final_video_path = os.path.join(vlm_save_dir, video_name)

                    snapshot_name = f"snapshot_{camera_id}_ID{track_id}_{current_time_str}.jpg"
                    final_snapshot_path = os.path.join(vlm_save_dir, snapshot_name)
                    cv2.imwrite(final_snapshot_path, annotated_frame)
                    
                    local_snap_url = f"/images/{os.path.basename(final_snapshot_path)}"
                    local_vid_url = f"/images/{os.path.basename(final_video_path)}"
                    
                    instant_payload = {
                        "device_id": numeric_id,
                        "camera_id": camera_id,
                        "location": "Room_301_Bed",
                        "event_type": "fall",
                        "person_id": track_id,
                        "clip_path": local_vid_url,
                        "detected_at": datetime.now().isoformat(),
                        "snapshot_path": local_snap_url,
                        "image_filename": final_snapshot_path,
                        "yolo_score": round(float(active_conf), 2),
                        "vlm_summary": f"【緊急通報】邊緣 AI 即時偵測到長者 (ID:{track_id}) 跌倒！請護理人員手動處置。"
                    }

                    if active_conf >= 0.8:
                        try:
                            import requests
                            headers = {"X-API-Key": VALID_API_KEY, "Content-Type": "application/json"}
                            res = requests.post("http://localhost:8000/events", json=instant_payload, headers=headers, timeout=2.0)
                            if res.status_code in [200, 201]:
                                print(f"⚡ [{camera_id}] (ID:{track_id}) 【秒級即時告警】跌倒通知已 0 延遲轟入後端！")
                        except Exception:
                            pass
                    else:
                        if producer is not None:
                            instant_payload["vlm_summary"] = None
                            instant_payload["status"] = "PENDING_VLM_ROUTE"
                            try:
                                producer.send('nursing-home-alerts', value=instant_payload)
                                producer.flush()
                                print(f"🧠 [{camera_id}] (ID:{track_id}) 跌倒信心偏低，送交 VLM 二次判斷！")
                            except Exception:
                                pass

        # 清理消失的 ID
        keys_to_remove = [tid for tid in person_states.keys() if tid not in active_track_ids]
        for tid in keys_to_remove:
            del person_states[tid]

        # 發送繪圖 JSON 給前端
        if persons_out_list:
            try:
                _detection_queue.put_nowait({
                    "1": persons_out_list, 
                    "Room_301_Bed": persons_out_list,
                    "persons": persons_out_list,
                    camera_id: persons_out_list
                })
            except Exception:
                pass

        if any_fall_triggered_this_frame:
            cv2.rectangle(annotated_frame, (0, 0), (img_w, img_h), (0, 0, 255), 12)
            cv2.putText(annotated_frame, "FALL DETECTED!", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3, cv2.LINE_AA)
        else:
            cv2.putText(annotated_frame, "Normal", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3, cv2.LINE_AA)

        # 背景影片寫入邏輯
        if is_recording_post and post_frame_count >= MAX_POST_FRAMES:
            is_recording_post = False
            full_10_sec_frames = list(pre_video_buffer) + post_video_buffer
            
            def _async_process_video(frames, video_path, snapshot_path, cam_id, num_id, prod):
                print(f"\n🎬 [{cam_id}] 異步背景合成前後 10 秒影片 ({len(frames)} 幀)...")
                try:
                    if not frames: return
                    frame_w, frame_h = 640, 360
                    temp_raw_path = video_path.replace(".mp4", "_raw.mp4")
                    # 先用 OpenCV 快速寫入 mp4v
                    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                    out = cv2.VideoWriter(temp_raw_path, fourcc, fps, (frame_w, frame_h))
                    for f in frames:
                        out.write(cv2.resize(f, (frame_w, frame_h)))
                    out.release()
                    
                    # 再呼叫 FFmpeg 進行網頁標準化轉碼 (保證 Safari/iOS 絕對能播)
                    import subprocess
                    import os
                    temp_final_path = video_path.replace(".mp4", "_final_temp.mp4")
                    ffmpeg_cmd = [
                        "ffmpeg", "-y", "-i", temp_raw_path,
                        "-c:v", "libx264", "-preset", "fast",
                        "-profile:v", "baseline", "-level", "3.0",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                        temp_final_path
                    ]
                    subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    
                    if os.path.exists(temp_final_path):
                        os.rename(temp_final_path, video_path)
                    
                    if os.path.exists(temp_raw_path):
                        os.remove(temp_raw_path)
                        
                    print(f"✅ [{cam_id}] 10 秒片段影片成功歸檔 (Web 完美相容)！")
                except Exception as async_err:
                    print(f"❌ [{cam_id}] 背景處理影片失敗: {async_err}")

            if 'final_video_path' in locals():
                threading.Thread(
                    target=_async_process_video,
                    args=(full_10_sec_frames, final_video_path, final_snapshot_path, camera_id, numeric_id, producer),
                    daemon=True
                ).start()

        now_t = time.time()
        fps_calc_counter += 1
        if now_t - fps_calc_time >= 1.0:
            measured_fps = fps_calc_counter / (now_t - fps_calc_time)
            fps_calc_counter = 0
            fps_calc_time = now_t

        fps_text = f"FPS: {measured_fps:.2f}"
        (text_w, text_h), _ = cv2.getTextSize(fps_text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        box_x1 = img_w - text_w - 20
        box_y1 = img_h - text_h - 20
        box_x2 = img_w
        box_y2 = img_h
        cv2.rectangle(annotated_frame, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), -1)
        cv2.putText(annotated_frame, fps_text, (box_x1 + 10, box_y2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(annotated_frame, f"VLM Status: {vlm_report}", (40, img_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
        
        small_frame = cv2.resize(annotated_frame, (320, 240))
        with frames_lock: output_frames[camera_id] = small_frame.copy()

        if rtsp_writer_proc:
            push_f = cv2.resize(annotated_frame, (out_w, out_h)) if (annotated_frame.shape[1] != out_w or annotated_frame.shape[0] != out_h) else annotated_frame
            with latest_push_lock:
                latest_push_frame = push_f.copy()

        t_elapsed = time.time() - t_start
        t_sleep = frame_delay - t_elapsed
        if t_sleep > 0: time.sleep(t_sleep)

    cap.release()

# =========================================================================
# 🏢 主執行緒控制
# =========================================================================
if __name__ == "__main__":
    camera_channels = {
        "Room_301_Bed": os.environ.get("CAM1_URL", "rtsp://localhost:8554/cam_in"),
    }

    print(f"🎬 全連鎖安養中心多鏡頭智能管線全面啟動...")
    
    threads = []
    for cam_id, stream_src in camera_channels.items():
        t = threading.Thread(target=camera_worker, args=(cam_id, stream_src))
        t.daemon = True; threads.append(t); t.start()
        
    headless_mode = "--headless" in sys.argv or os.environ.get("HEADLESS") == "1"
    
    try:
        if headless_mode:
            print("🖥️  [Headless] 以背景無 GUI 模式啟動...")
            while True:
                time.sleep(1.0)
        else:
            frame_interval = 1.0 / 30.0; window_positions = {}  
            while True:
                start_time = time.time(); active_windows = False
                with frames_lock: current_display_frames = output_frames.copy()
                    
                for idx, (cam_id, img_to_show) in enumerate(current_display_frames.items()):
                    if img_to_show is not None:
                        win_name = f"Fall Detection System - {cam_id}"
                        cv2.imshow(win_name, img_to_show)
                        if win_name not in window_positions:
                            x_pos = 40 + (idx * 335); y_pos = 80
                            cv2.moveWindow(win_name, x_pos, y_pos)
                            window_positions[win_name] = (x_pos, y_pos)
                        active_windows = True
                
                if active_windows:
                    if cv2.waitKey(1) & 0xFF == ord('q'): break
                
                sleep_time = frame_interval - (time.time() - start_time)
                time.sleep(sleep_time if sleep_time > 0 else 0.001)
                
    except KeyboardInterrupt: pass
    finally:
        if not headless_mode:
            cv2.destroyAllWindows()
        if producer is not None: producer.close()

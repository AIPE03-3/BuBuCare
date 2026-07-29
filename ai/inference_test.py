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
# 🌟 外掛模組（白名單制，見根目錄 CLAUDE.md）
# =========================================================================
# 2026-07-27 起 ai/modules/ 只准存在、也只准 import 兩個檔：__init__.py 與 sanity_check.py。
# 原本的 bed_exit / wandering / micro_motion / audio_fusion / chair_slip 五個模組已刪除，
# 功能與邏輯一律不再套用。理由（詳見 CLAUDE.md）：
#   · 前三個各自繞過 route_by_confidence() 自組 payload 直送 Kafka，欄位對不上契約，
#     每一則都被後端 422 退件（2026-07-27 用 test4.mp4 實測確認）。
#   · audio_fusion 是展示用的假資料產生器（對 camera_id 含 "303" 的相機每 22 秒隨機
#     丟「撞擊聲/呼救」並把信心強制拉到 0.96 直入快速道），是誤報來源不是偵測能力。
#   · 本階段只保留跌倒機制。跌倒主邏輯在下面 camera_worker 的主迴圈裡（防線 A 體角判定、
#     防線 B 幾何遮擋、AcT 時序分類），從來就不在 modules/ 底下，不受這次收斂影響。
# 護欄 scripts/check_guardrails.py 會擋掉任何新增檔案或 import，不是只靠這段註解。
from modules.sanity_check import RoutineSanityChecker  # 模組 G：VLM 閒置算力環境安全巡檢

from triton_pose_client import TritonPoseModel          # Triton 版 yolo_pose client（人體姿態）
from triton_detr_client import TritonDetrModel          # Triton 版 rt_detr client（環境物件偵測）
from triton_act_client import TritonActModel            # Triton 版 action_transformer client（時序跌倒分類）

from av_reader import open_source, is_stream_source       # AV1 影片解碼（PyAV），介面對齊 cv2.VideoCapture
from backend_devices import (                             # 從後端裝置表取真實攝影機清單
    build_camera_channels, build_detect_channels, fetch_devices, login,
    BackendUnavailable, BACKEND_API_URL, cfg,
)
from detect_publisher import make_publisher               # 把畫好框的畫面推回 MediaMTX 偵測頻道

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


def route_by_confidence(*, act_confidence, is_occluded_fall,
                        event_label, numeric_id, clip_path, detected_at,
                        snapshot_full_path, snapshot_name, final_score, yolo_thresh):
    """依 AcT 信心把單一跌倒事件路由到對應 Kafka topic，回傳 (topic, payload)。

    這是 C 組信心分流的乾淨抽離點（原本寫死在 camera_worker 裡的 if/else）：
      - 高信心（act_confidence >= FAST_TRACK_CONF）且非遮擋不確定
        → (processed-reports, 快速道 payload)：後端 consumer 直接落 PostgreSQL，不經 VLM。
      - 其餘（信心不足 / 遮擋難判）
        → (nursing-home-alerts, 待審 payload)：走 Kafka → vlm_worker 二審 → 回 processed-reports。

    2026-07-27：原本還有一個 `is_chair_slipped` 參數（模組 I 判定座椅滑落時強制走快速道，
    event_type 送 "chair_slip"）。該模組已隨 ai/modules/ 白名單收斂刪除（見檔頭與 CLAUDE.md），
    參數一併移除、`event_type` 從此恆為 "fall"。**payload 欄位一個字都沒動**——
    護欄 scripts/check_guardrails.py 檢查的是下面兩個 payload dict 的 keys，不是本函式簽章。

    兩個 payload 的欄位**不一樣**，因為去向不一樣：
      - 快速道走 processed-reports，會被後端 consumer 直接轉成 POST /events，所以只帶
        後端認得的欄位（device_id(int)/event_type/detected_at(ISO)/snapshot_path/
        yolo_score/vlm_summary，外加後端忽略但 AI 端自己要用的 image_filename）。
      - 慢速道走 nursing-home-alerts，收件人是 vlm_worker / agent（都是 AI 內部），
        所以多帶一個 yolo_threshold —— agent 的 judge prompt 要拿它跟 yolo_score 比大小
        （見 agent/prompts.py:describe_score_vs_threshold，那是防地端小模型比錯的防呆）。
        二審完成後 vlm_worker 重組外發 payload 時不會把它帶去後端。
      - severity 兩條都不送：後端已於 2026-07-19（commit 1bbb585）移除該欄位，
        嚴重度概念改用 verdict_by / resolved_by 取代。

    第 2 層 LangGraph Uncertainty Router 之後可直接 import 本函式接管路由決策，
    介面不變（VLMModel.infer 已隔離、與此對齊）。

    `clip_path` 收的是**事件片段**的位置（見 write_event_clip）。以前這裡收的是
    `video_source`——影片檔時代那就是那支 mp4 還說得過去，但接上 RTSP 之後會變成一個
    `rtsp://` 網址，前端點下去沒有「事發當時」可看。欄位名是契約不動，只換裡面的值。
    """
    is_fast_track = act_confidence >= FAST_TRACK_CONF and not is_occluded_fall

    if is_fast_track:
        # 🟢 分流 A：快速道路（Critical_Fast_Track）——高信心，直入後端落庫。
        # 這條直接進後端，只帶後端要的欄位；不帶 yolo_threshold（AI 內部用的門檻值）。
        payload = {
            "device_id": numeric_id,
            "event_type": event_label,
            "clip_path": str(clip_path),
            "detected_at": detected_at,
            "snapshot_path": snapshot_full_path,
            "image_filename": snapshot_name,
            "yolo_score": final_score,
            "vlm_summary": "【緊急通報】邊緣端偵測到嚴重跌倒！請立刻前往救援。",
        }
        return TOPIC_PROCESSED_REPORTS, payload

    # 🔵 分流 B：慢速道路（Pending_VLM_Review）——信心不足/遮擋難判，送 VLM 二審。
    # 收件人是 AI 內部（vlm_worker / agent），故多帶 yolo_threshold 供二審端比對信心用。
    payload = {
        "device_id": numeric_id,
        "event_type": event_label,
        "clip_path": str(clip_path),
        "detected_at": detected_at,
        "snapshot_path": snapshot_full_path,
        "image_filename": snapshot_name,
        "yolo_score": final_score,
        "yolo_threshold": yolo_thresh,   # 只在 AI 內部流通，二審端不會把它外發後端
        "vlm_summary": "【AI 信心度不足】已觸發大模型二審，正在分析影像特徵並生成詳細報告...",
    }
    return TOPIC_NURSING_HOME_ALERTS, payload

# =========================================================================
# 📼 事件片段存檔：跌倒瞬間前 PRE 秒 + 後 POST 秒
# =========================================================================
# 為什麼要這個：`clip_path` 以前塞的是「影像來源本身」。影片檔時代那就是那支 mp4，
# 接上 RTSP 之後會變成一個 rtsp:// 網址 —— 前端點下去根本沒有事發當時的畫面可看。
# 改成把觸發瞬間前後各數秒寫成一段獨立影片，`clip_path` 指向它。
#
# 全部走設定、未設＝保守預設，不動任何既有開關的行為。
# 用 backend_devices.cfg 而不是 os.environ.get：專案的 .env 是用 dotenv_values 讀成 dict
# （刻意不注入 os.environ，見 backend_devices 檔頭），只讀 os.environ 會完全看不到 .env 的設定。
_CLIP_PRE_SEC = float(cfg("CLIP_PRE_SEC", "5"))
_CLIP_POST_SEC = float(cfg("CLIP_POST_SEC", "5"))
# 畫面上「FALL DETECTED!」紅框在最後一次觸發後還要顯示多久。
# 為什麼需要這個而不是「偵測到就一直紅」：紅框原本掛在 ever_detected_fall 這個只進不出的
# 旗標上，第一次觸發之後畫面就永遠是紅的，值班人員再也無法從畫面判斷現在有沒有事——
# 接真攝影機（worker 一跑好幾天）等於這個指示燈失效。實測用手機當攝影機時複現。
# 也不能純粹看當下那一幀：偵測會逐幀跳動，紅框會閃爍到無法判讀。故用「保持數秒」。
_FALL_DISPLAY_HOLD_SEC = float(cfg("FALL_DISPLAY_HOLD_SEC", "10"))
# 多人畫面時「逐人幾何判定」log 的最小間隔（秒）。防線 A/B 逐人化後，現場需要知道
# 被判倒地的是誰、是不是又落在最大框那位身上；但逐幀印會刷屏（每秒十幾行），故節流。
# 單人畫面完全不印，log 乾淨度與改動前相同。
_MULTI_LOG_MIN_GAP_SEC = float(cfg("MULTI_PERSON_LOG_SEC", "3"))
# 緩衝存的是「原始幀」（塞在跳幀之前），1080p 全解析度下前後 10 秒每台相機要吃 ~1.8GB，
# 多路併發直接 OOM。故片段緩衝獨立降寬——推論吃的仍是原圖，完全不受影響。
# H.264 要求邊長為偶數，故抹掉奇數位。設 0＝不縮放（記憶體自負）。
_CLIP_WIDTH = int(cfg("CLIP_WIDTH", "640"))
_CLIP_WIDTH -= _CLIP_WIDTH % 2
_CLIP_DIR = cfg("CLIP_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "clips"
)
# 後端 GET /events/{id}/media 只認 s3://（backend/core/s3.py 的 generate_presigned_url
# 對非 s3:// 一律回 None），所以本地路徑前端是拿不到可播網址的。
# 設了 bucket 就上傳並讓 clip_path 帶 s3:// URI；沒設就退回本地路徑 —— 沒有 AWS 憑證的
# 機器照樣跑得動、不會在跌倒當下噴錯，只是前端暫時拿不到影片。
_CLIP_S3_BUCKET = cfg("CLIP_S3_BUCKET").strip()
_CLIP_S3_PREFIX = cfg("CLIP_S3_PREFIX", "videos").strip("/")
# AWS 憑證：本檔只做一件 S3 動作——把事件片段 upload_file 上去，需要 PutObject（寫）。
# 後端 backend/core/s3.py 只做 presigned GET（讀），兩邊刻意用不同金鑰＝最小權限，
# 不是重複設定：
#   · S3_RW_*（讀寫）      → 本檔上傳片段用。2026-07-27 實測 put/head/get/delete 全通。
#   · ACCESS_KEY_ID 等（唯讀）→ 後端簽 presigned URL 用，一行不動。同日實測該組簽出的
#                              URL 對本檔上傳的物件回 HTTP 200，前端拿得到可播網址。
# 沒設 S3_RW_* 的機器（Mac / CI）自動 fallback 回舊名，行為與改動前完全一樣。
# 變數名都不是 boto3 標準的 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY，故必須顯式傳進
# client；留空則傳 None，退回預設憑證鏈（EC2/GCP VM 的 IAM role 走這條）。
_S3_REGION = cfg("S3_RW_REGION") or cfg("S3_REGION")
_S3_ACCESS_KEY = cfg("S3_RW_ACCESS_KEY_ID") or cfg("ACCESS_KEY_ID")
_S3_SECRET_KEY = cfg("S3_RW_SECRET_ACCESS_KEY") or cfg("SECRET_ACCESS_KEY")


def _downscale_for_clip(frame):
    """把要進片段緩衝的幀等比縮到 _CLIP_WIDTH 寬（只縮不放）。"""
    if _CLIP_WIDTH <= 0:
        return frame
    h, w = frame.shape[:2]
    if w <= _CLIP_WIDTH:
        return frame
    new_h = int(round(h * _CLIP_WIDTH / w))
    new_h -= new_h % 2  # H.264 要求偶數邊長
    return cv2.resize(frame, (_CLIP_WIDTH, max(new_h, 2)), interpolation=cv2.INTER_AREA)


def _video_fourcc(code):
    """OpenCV 4.x 是 `cv2.VideoWriter_fourcc`，5.x 移到 `cv2.VideoWriter.fourcc`。

    本專案兩台開發機版本不同（macOS 這台是 5.0.0，Windows 那台通常是 4.x），
    寫死任一邊都會在另一邊 AttributeError。
    """
    fn = getattr(cv2, "VideoWriter_fourcc", None) or cv2.VideoWriter.fourcc
    return fn(*code)


def _write_frames_h264_pyav(frames, out_path, fps):
    """用 PyAV（libx264）把 BGR 幀寫成瀏覽器播得動的 H.264 mp4；成功回 True。

    為什麼需要這條路：OpenCV 的 `avc1` 能不能開，取決於那顆 OpenCV 帶的 ffmpeg 選到哪個
    H.264 編碼器。WSL2 這台選到 `h264_v4l2m2m`（V4L2 硬體編碼器），而 WSL2 沒有那個裝置：

        [h264_v4l2m2m] Could not find a valid device
        [ERROR] Could not open codec h264_v4l2m2m ... Failed to initialize VideoWriter

    於是每一支片段都靜靜地退到 `mp4v`（MPEG-4 Part 2）。檔案寫得出來、一般播放器也開得起來，
    所以 log 全綠、S3 上傳成功、後端 presigned URL 回 200 —— **只有瀏覽器播不動**，
    前端事件詳情頁的 <video> onError 之後只剩「案件片段影像」五個字。
    2026-07-29 實測：`ai/clips/` 裡當時的 18 支片段全部都是 mpeg4，等於前端從來沒播成功過。

    PyAV 是本專案既有依賴（`av_reader.py` 就在用），其 wheel 自帶 libx264，不需要系統裝
    ffmpeg，也就不受上面那個硬體編碼器的影響。
    """
    import av  # 與 boto3 同樣 lazy import：這條路沒被走到的機器不必為它付出 import 成本

    h, w = frames[0].shape[:2]
    # yuv420p 要求邊長為偶數（_downscale_for_clip 已抹掉寬的奇數位，但 CLIP_WIDTH=0
    # 不縮放時高仍可能是奇數）。多切掉一列/一行比讓編碼器整支失敗划算。
    w -= w % 2
    h -= h % 2
    container = av.open(out_path, "w")
    try:
        stream = container.add_stream("libx264", rate=max(1, int(round(fps))))
        stream.width, stream.height = w, h
        stream.pix_fmt = "yuv420p"
        # faststart：moov atom 搬到檔頭，瀏覽器不必下載完整支才能開始播。
        stream.options = {"movflags": "+faststart", "preset": "veryfast", "crf": "23"}
        for f in frames:
            frame = av.VideoFrame.from_ndarray(f[:h, :w], format="bgr24")
            for pkt in stream.encode(frame):
                container.mux(pkt)
        for pkt in stream.encode():   # flush 編碼器內部緩衝，少了會掉尾巴幾幀
            container.mux(pkt)
    finally:
        container.close()
    return True


def write_event_clip(frames, out_path, fps, camera_id, s3_key=None):
    """把 frames 寫成 mp4；設了 CLIP_S3_BUCKET 就再上傳一份。

    給背景 daemon thread 跑：寫檔（尤其還要上傳）是秒級 I/O，卡在推論迴圈裡會讓
    該路相機掉幀。整支包在 try 內 —— 片段存檔失敗不該影響已經發出去的警報。
    """
    if not frames:
        return
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        h, w = frames[0].shape[:2]
        # 編碼器三段式：avc1（OpenCV）→ libx264（PyAV）→ mp4v（最後手段）。
        # 前兩段都是 H.264＝瀏覽器播得動；只有兩段都失敗才退 mp4v，並且**明講**退了，
        # 因為 mp4v 的症狀是「一切正常但前端播不出來」，不印出來就查不到（見
        # _write_frames_h264_pyav 的說明）。
        codec_used = "avc1 (OpenCV)"
        writer = cv2.VideoWriter(out_path, _video_fourcc("avc1"), fps, (w, h))
        if writer.isOpened():
            for f in frames:
                writer.write(f)
            writer.release()
        else:
            writer.release()
            try:
                _write_frames_h264_pyav(frames, out_path, fps)
                codec_used = "libx264 (PyAV)"
            except Exception as e:
                print(f"⚠️ [{camera_id}] PyAV libx264 寫檔失敗，改用 mp4v：{e}")
                writer = cv2.VideoWriter(out_path, _video_fourcc("mp4v"), fps, (w, h))
                if not writer.isOpened():
                    print(f"❌ [{camera_id}] 片段寫檔失敗：avc1 / libx264 / mp4v 都開不起來 → {out_path}")
                    return
                for f in frames:
                    writer.write(f)
                writer.release()
                codec_used = "mp4v ⚠️ 非 H.264，瀏覽器 <video> 播不動"
        print(f"🎬 [{camera_id}] 事件片段已寫入（{len(frames)} 幀 @ {fps:.1f}fps，{codec_used}）：{out_path}")

        if not s3_key:
            return
        # lazy import：沒設 CLIP_S3_BUCKET 的機器不必裝 boto3、也不必有 AWS 憑證。
        import boto3
        boto3.client(
            "s3",
            region_name=_S3_REGION or None,
            aws_access_key_id=_S3_ACCESS_KEY or None,
            aws_secret_access_key=_S3_SECRET_KEY or None,
        ).upload_file(
            out_path, _CLIP_S3_BUCKET, s3_key, ExtraArgs={"ContentType": "video/mp4"}
        )
        print(f"📦 [{camera_id}] 片段已上傳：s3://{_CLIP_S3_BUCKET}/{s3_key}")
    except Exception as e:
        print(f"❌ [{camera_id}] 事件片段處理失敗（警報已發出，不受影響）：{e}")

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
# 位址走 cfg()（環境變數優先、其次 repo 根目錄的 .env），與本檔其他設定一致。
# ⚠ 預設埠是 8010 不是 8000：8000 在本專案被 backend 佔用。曾經預設 8000，結果是每一幀
# 都打到 FastAPI、拿回 {"detail":"Not Found"} 後靜默降級 —— 影片照跑、FPS 照印、沒有紅字，
# 但姿態偵測全程失效。這種失敗方式從輸出完全看不出來，所以預設值必須是對的那個。
TRITON_HOST = cfg("TRITON_HOST", "http://127.0.0.1:8010").rstrip("/")
TRITON_POSE_URL = cfg("TRITON_POSE_URL") or f"{TRITON_HOST}/yolo_pose"
TRITON_DETR_URL = cfg("TRITON_DETR_URL") or f"{TRITON_HOST}/rt_detr"
TRITON_ACT_URL = cfg("TRITON_ACT_URL") or f"{TRITON_HOST}/action_transformer"
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
def camera_worker(camera_id, video_source, detect_url=None):
    global producer, device, yolo_pose_model, yolo_env_model, transformer_model, output_frames, frames_lock

    print(f"🚀 鏡頭頻道 [{camera_id}] 啟動拉流：{video_source}")
    # 影片檔（AV1）走 PyAV 解碼、webcam index 走 cv2；介面與 cv2.VideoCapture 相同。
    # 即時串流（rtsp/rtmp/http）要斷線自動重連；影片檔維持「播完就結束」，不無限重播。
    _is_stream = is_stream_source(video_source)
    _backoff_max = float(os.environ.get("RTSP_RECONNECT_MAX_BACKOFF", "30"))

    def _fps_of(c):
        f = c.get(cv2.CAP_PROP_FPS)
        if f <= 0 or np.isnan(f): f = 30.0
        return f

    def _reconnect():
        """指數退避重連：1→2→4→8→16→30s 封頂，無限重試，拿到可用 reader 才回。

        每次重試都要新建 reader，不能沿用舊的：AVStreamReader 判定斷流後 _consec_fail
        永不歸零、PrefetchReader 的 _eof_seen 也是永久閂鎖，舊物件已經死透。
        """
        delay, attempt, t_down = 1.0, 1, time.time()
        while True:
            new_cap = open_source(video_source)
            if new_cap.isOpened():
                print(f"✅ [{camera_id}] 重連成功（第 {attempt} 次嘗試，中斷 {time.time() - t_down:.0f}s）：{video_source}")
                return new_cap
            # 開失敗也要 release：DECODE_PREFETCH 下建構子已經起了背景執行緒，
            # 不 release 就是每次重試漏一條 thread + 一個 socket。
            new_cap.release()
            print(f"🔁 [{camera_id}] 重連第 {attempt} 次失敗，{delay:.0f}s 後再試（退避上限 {_backoff_max:.0f}s）：{video_source}")
            time.sleep(delay)
            delay = min(delay * 2, _backoff_max)
            attempt += 1

    cap = open_source(video_source)
    if not cap.isOpened():
        if not _is_stream:
            print(f"❌ 鏡頭頻道 [{camera_id}] 無法開啟影像源: {video_source}")
            return
        cap.release()
        print(f"🔌 [{camera_id}] 首次連線失敗（攝影機可能還沒開機），進入自動重連：{video_source}")
        cap = _reconnect()

    source_fps = _fps_of(cap)
    frame_delay = 1.0 / source_fps

    # ── 📤 偵測畫面推流（前端「即時／偵測」切換鈕的「偵測」那一半）────────
    # 推的是下面 Step D 畫好的 annotated_frame。沒設 DETECT_STREAM=1、該相機沒有
    # stream_channel_detect、或機器上沒有 ffmpeg 時一律回 None，迴圈內就不會推。
    # ⚠ 這條出口與事件片段/快照完全無關：那兩者刻意維持無框的原始畫面（組長決策：
    #    彈窗當下有框會干擾人工確認），別把 annotated_frame 接進 write_event_clip。
    detect_pub = make_publisher(camera_id, detect_url, fps=source_fps)

    # ── 📼 事件片段緩衝（觸發前 PRE 秒 / 後 POST 秒）──────────────────────
    # 緩衝塞在 `frame_count % 2` 跳幀之前，存的是原始幀：存已處理幀的話同樣的秒數
    # 只會收到一半份量的畫面，寫出來的片段時間軸整個對不上。
    _max_pre_frames = max(1, int(source_fps * _CLIP_PRE_SEC))
    _max_post_frames = max(1, int(source_fps * _CLIP_POST_SEC))
    pre_clip_buffer = deque(maxlen=_max_pre_frames)  # 環形：永遠只留最近 PRE 秒
    pre_clip_snapshot = None   # 觸發瞬間對 pre buffer 拍下的快照（見觸發段的說明）
    post_clip_buffer = []      # 觸發後續錄；寫檔後立刻斷開參照釋放記憶體
    is_recording_post = False
    clip_local_path = None
    clip_s3_key = None

    frame_window = deque(maxlen=30)
    vlm_triggered = False
    vlm_report = "Waiting for alert..."
    
    last_pose_feat = np.zeros(34, dtype=np.float32)
    has_seen_person = False
    last_valid_annotated_frame = None
    frame_count = 0
    normal_h_reference = None
    triton_down_warned = False  # Triton 斷線降級提示只印一次，避免逐幀刷屏
    _multi_log_t = 0.0          # 上次印「多人逐人判定」的時刻（節流用，見下方主迴圈）

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
    if _no_render and detect_pub is not None:
        # 偵測推流推的就是 Step D 畫出來的那張圖，NO_RENDER 等於把來源整個關掉。
        # 這兩個開關同時設一定是誤會，講明白比默默推出一片空白好。
        print(f"⚠️ [{camera_id}] NO_RENDER=1 會跳過畫框渲染，偵測推流沒有畫面可推 → 停用推流"
              f"（要推流請拿掉 NO_RENDER）")
        detect_pub.close()
        detect_pub = None
    # 提速：DETR_EVERY_N=N（N>1）把 rt_detr 環境物件偵測降頻成「每 N 個處理幀才跑一次」，
    # 其餘幀復用上次結果。detr 佔 ~30% 幀時間，但它偵測的全是靜態家具（bed/chair/couch…），
    # results_env 三個下游用途（bed_box 離床、chair_box 座椅滑落、mask 疊圖）都只是
    #「空間參考框」，家具不會動、幾秒不更新沒差；pose 則必須每幀跑（要餵連續 30 幀給 AcT，
    # 時序不能有洞）故完全不動。未設＝1＝位元級原本的每幀行為，隨時可退回。
    _detr_every_n = max(1, int(os.environ.get("DETR_EVERY_N", "1")))
    _detr_proc_idx = 0          # 已處理幀計數（只給 detr 降頻用，與 FPS 計數解耦）
    _cached_results_env = None  # 上次 detr 結果，跳過的幀復用
    _fps_t0 = time.time()
    _fps_n = 0            # 本區間已處理幀數
    _fps_proc_total = 0   # 累計已處理幀數
    _fps_run_t0 = time.time()
    
    # 💡 狀態旗標
    ever_detected_fall = False  # 模組 C：全域歷史記憶鎖旗標（「曾經發生過」，只進不出）
    fall_display_until = 0.0    # 畫面紅框顯示到這個時刻為止（見 _FALL_DISPLAY_HOLD_SEC）
    
    # 💡 白名單內唯一的外掛模組（其餘五個已刪，見檔頭與 CLAUDE.md）
    # 間隔拉長的原因：巡檢原本靠 `not is_leaving_bed and not is_wandering` 兩個旗標抑制，
    # 那兩個模組刪掉後旗標恆為 False，等於少了兩道閘門。若維持 15 秒，閒置時每 15 秒就有
    # 一張圖進 nursing-home-alerts；而 uncertainty_router 是「一律二審不加 discard」、
    # vlm_worker 每筆二審完成都外發 processed-reports，後端就會每 15 秒多一筆巡檢事件。
    # 用環境變數可調，未設＝60 秒。（sanity_check.py 本身一行未動，間隔是呼叫端給的參數。）
    sanity_checker = RoutineSanityChecker(
        camera_id, interval_seconds=float(cfg("SANITY_INTERVAL_SEC", "60"))
    )

    while True:
        t_start = time.time()
        ret, frame = cap.read()
        
        if not ret:
            # 即時串流的 (False, None) 不是「播完了」，是上游斷了（攝影機重開機、網路抖、
            # 交換器重啟）。丟掉死掉的 reader、退避重連，不能像影片檔那樣收工。
            if _is_stream:
                print(f"🔌 [{camera_id}] 串流中斷，開始自動重連：{video_source}")
                cap.release()
                cap = _reconnect()
                source_fps = _fps_of(cap)            # 重連後 fps 可能重新協商過
                frame_delay = 1.0 / source_fps
                # 片段緩衝的「秒數 → 幀數」換算要跟著新 fps 重算。deque 的 maxlen 不能
                # 改，用現有內容重建一個（斷線前那幾秒畫面留著，不平白丟掉）。
                _max_pre_frames = max(1, int(source_fps * _CLIP_PRE_SEC))
                _max_post_frames = max(1, int(source_fps * _CLIP_POST_SEC))
                if pre_clip_buffer.maxlen != _max_pre_frames:
                    pre_clip_buffer = deque(pre_clip_buffer, maxlen=_max_pre_frames)
                # 錄到一半斷線：後段會缺一塊，硬接起來就是時間跳斷的假片段。中止本次錄影。
                # vlm_triggered 仍為 True，維持現有「重連不重複發報」的性質不變。
                if is_recording_post:
                    print(f"🎞️ [{camera_id}] 片段錄製中斷線，中止本次後段錄影（避免拼出時間跳斷的片段）")
                    is_recording_post = False
                    pre_clip_snapshot = None
                    post_clip_buffer = []
                # 時序連續性已斷 → 清空餵 AcT 的 30 幀視窗。把斷線前最後一幀直接接上斷線後
                # 第一幀，等於偽造一個瞬間姿態跳變，那正是 AcT 判定跌倒的特徵，會誤報。
                # 既有的 len<30 → "Buffering" 路徑會自然接手，累滿 30 幀後恢復判定。
                frame_window.clear()
                last_pose_feat = np.zeros(34, dtype=np.float32)
                has_seen_person = False
                # 別讓中斷時間污染下一段區間 FPS（否則會印出荒謬的 <1 fps 像是退化）。
                # normal_h_reference / frame_count / ever_detected_fall / 六個偵測器物件
                # 一律保留：相機沒換人也沒移位，重設只會讓防線失效或對同一起事件重複發報。
                _fps_t0 = time.time(); _fps_n = 0
                print(f"♻️ [{camera_id}] 時序視窗已清空，重新累積 30 幀後恢復 AcT 判定")
                continue
            # 影片檔播完但後段還沒錄滿：clip_path 早已隨警報發出去了，不能讓它指向一個
            # 永遠不存在的檔案。有多少寫多少（片段會短於 POST 秒，但至少存在）。
            # 這裡同步寫、不丟背景執行緒：worker 收工後行程可能跟著結束，daemon thread 會被砍。
            if is_recording_post:
                print(f"🎞️ [{camera_id}] 影像流結束，後段未錄滿 → 補寫已收到的片段")
                write_event_clip((pre_clip_snapshot or []) + post_clip_buffer,
                                 clip_local_path, source_fps, camera_id, clip_s3_key)
                is_recording_post = False
                pre_clip_snapshot = None
                post_clip_buffer = []
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

        # ──  片段緩衝：擺在跳幀之前，存的是原始幀（降寬後）──────────────────
        _clip_frame = _downscale_for_clip(frame)
        pre_clip_buffer.append(_clip_frame)
        if is_recording_post:
            post_clip_buffer.append(_clip_frame)
            if len(post_clip_buffer) >= _max_post_frames:
                # 後段收滿 → 丟背景執行緒寫檔，主迴圈立刻回去跑推論。
                #  前段用「觸發當下拍的快照」而不是此刻的 pre_clip_buffer：pre buffer
                #    每幀都在滾，錄完後段時它裡面裝的已經正好是後段那批幀，直接取會拼出
                #    「後 N 秒 ×2」的假片段（albert 分支的實作就是踩在這個坑上）。
                threading.Thread(
                    target=write_event_clip,
                    args=((pre_clip_snapshot or []) + post_clip_buffer,
                          clip_local_path, source_fps, camera_id, clip_s3_key),
                    daemon=True,
                ).start()
                is_recording_post = False
                pre_clip_snapshot = None
                post_clip_buffer = []  # 斷開參照，別讓 10 秒份的幀留在記憶體

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
            print(f" [FPS/{_mode}] [{camera_id}] 區間 {_inst:5.1f} fps｜累計均 {_avg:5.1f} fps"
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
                print(f" [{camera_id}] Triton pose 推論失敗（降級：略過此幀，持續重試）：{e}")
                triton_down_warned = True
            t_sleep = frame_delay - (time.time() - t_start)
            if t_sleep > 0: time.sleep(t_sleep)
            continue
        # rt_detr 降頻（DETR_EVERY_N）：只在每 N 個處理幀真的打一次 Triton，其餘幀復用快取。
        #  是「復用上次結果」而不是「傳 None」——results_env 的下游（模組 A 離床拿 bed_box、
        #    模組 I 座椅滑落拿 chair_box）都靠它當空間參考框，傳 None 會讓偵測時斷時續；
        #    家具靜態，復用幾幀前的框才是正確做法。N=1 時此分支恆真，行為與原本完全一致。
        if _detr_proc_idx % _detr_every_n == 0:
            try:
                results_env = yolo_env_model(frame, verbose=False, conf=0.35)  # rt_detr 環境物件偵測
            except Exception as e:
                if not triton_down_warned:
                    print(f"⚠️ [{camera_id}] Triton rt_detr 推論失敗（降級：本幀不做環境物件疊圖）：{e}")
                    triton_down_warned = True
                results_env = None  # 下游 `if results_env and ...` guard 可容忍 None
            # 失敗時的 None 也一併寫回快取：Triton 斷線就該讓下游看到 None，
            # 不能拿幾幀前的舊框假裝偵測還活著（保住原本的斷線降級語意）。
            _cached_results_env = results_env
        else:
            results_env = _cached_results_env
        _detr_proc_idx += 1

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
        is_whitespace = False
        # 多人獨立跌倒判定：防線 A/B 逐人各算一次的結果。
        #   person_fall_flags: [(idx, is_lying_i, is_occluded_i)]，保留每個人的旗標，
        #     供畫面標註（本次）與之後的前端逐人廣播（尚未做）使用。
        #   fall_person_boxes: 被判定跌倒者的 xyxy 框，Step D 拿去畫紅框。
        # 兩個都在這裡初始化（而不是在 results_pose 分支裡），確保沒偵測到人、或下面
        # try 落到 except 時，後面的 any()/畫圖仍拿得到一個空 list。
        person_fall_flags = []
        fall_person_boxes = []

        if results_pose and len(results_pose[0].keypoints) > 0:
            kpts_obj = results_pose[0].keypoints
            try:
                kpts_data = kpts_obj.xyn.cpu().numpy() 
                conf_data = results_pose[0].boxes.conf.cpu().numpy()  
                boxes_data = results_pose[0].boxes.xywh.cpu().numpy()  
                boxes_xyxy = results_pose[0].boxes.xyxy.cpu().numpy()
                
                if kpts_data.ndim == 3 and kpts_data.shape[0] > 0:
                    # ── 第 1 趟：挑出 best_idx（只給 AcT 用），順便收齊「通過門檻的所有人」──
                    # valid_idxs 的篩選條件與原本挑 best_idx 的條件一字不差，再加一個
                    # `idx < len(boxes_xyxy)`：防線 B 要用 xyxy，四個陣列
                    #（kpts_data / conf_data / boxes_data / boxes_xyxy）索引必須同時有效才收。
                    # 第 2 趟直接吃這份名單，避免兩處篩選條件日後各自漂移。
                    best_idx = -1; max_score = -1.0
                    valid_idxs = []
                    for idx in range(kpts_data.shape[0]):
                        if idx < len(conf_data) and conf_data[idx] < 0.45: continue
                        if idx < len(boxes_data) and idx < len(boxes_xyxy):
                            valid_idxs.append(idx)
                            _, _, w_box, h_box = boxes_data[idx]
                            score = conf_data[idx] * (w_box * h_box)
                            if score > max_score: max_score = score; best_idx = idx

                    if best_idx != -1:
                        # ── best_idx 專屬：餵 AcT 的 34 維特徵 ──────────────────────
                        # AcT 時序**刻意維持單人序列**：仍只餵 best_idx 一個人、單一 30 幀
                        # window、單次 Triton 呼叫。真正的逐人時序要有 tracker 才做得到
                        #（每條 track 各自一個 window），那是另一個題目。
                        # 空骨架防呆 np.all(temp_feat == 0) 與 last_pose_feat 補幀是綁在
                        #「餵 AcT 的那一個人」身上的邏輯，不套用到其他人。
                        kp = kpts_data[best_idx]
                        temp_feat = kp[:17, :2].flatten()
                        if not np.all(temp_feat == 0):
                            current_pose_feat = temp_feat.copy(); last_pose_feat = current_pose_feat.copy()
                            has_seen_person = True; is_current_frame_valid = True

                        _, _, w_box, h_box = boxes_data[best_idx]
                        # normal_h_reference：**維持單一參考值、全員共用**（這是選擇，不是漏改）。
                        #   為什麼不逐人各自校準：參考值的語意是「這個人站著時的正常身高」，
                        #   要累積它就得先知道「跨幀的哪個框是同一個人」＝ tracker。YOLO 的偵測
                        #   索引每幀都可能換人，照索引存參考值等於把 A 的身高記到 B 頭上，
                        #   比共用單一值更錯。本次範圍明確不引入 tracker。
                        #   代價（要知道）：離鏡頭遠、或本來就矮的人 h_box 天生小，比值可能
                        #   直接低於 0.70 而誤判。這是 NEXT_STAGE.md 第 9 節「缺陷三」那個
                        #   既有問題的擴大版（參考值只校準一次、換來源不重設），不是新機制。
                        #   既有的 `y2 > img_h*0.5` 條件仍在，擋掉一部分「遠處站著的人」
                        #  （框底落在畫面上半）。真要修，要跟缺陷三一起改，不在本次範圍。
                        if normal_h_reference is None and frame_count > 10 and frame_count < 40: normal_h_reference = h_box

                        # ── 第 2 趟：防線 A / B 對「每一個通過門檻的人」各算一次 ──────
                        # 原本兩道防線只算 best_idx（信心×面積最大的那個人）一個人，畫面裡
                        # 有兩個人、而跌倒的不是面積最大那位時（照顧者站著、被照顧者倒在
                        # 地上所以框小），兩個旗標都不會被設起來 → 整起事件不觸發，是漏報。
                        # 公式與門檻完全照舊，只是把 best_idx 換成逐人的 idx。
                        for idx in valid_idxs:
                            kp_i = kpts_data[idx]
                            _, _, w_box_i, h_box_i = boxes_data[idx]
                            x1, y1, x2, y2 = boxes_xyxy[idx]
                            is_lying_i = False
                            is_occluded_i = False

                            # 跌倒防線 A
                            try:
                                shoulder_x = (kp_i[5][0] + kp_i[6][0]) / 2.0; shoulder_y = (kp_i[5][1] + kp_i[6][1]) / 2.0
                                hip_x = (kp_i[11][0] + kp_i[12][0]) / 2.0; hip_y = (kp_i[11][1] + kp_i[12][1]) / 2.0
                                if not (shoulder_x == 0 or hip_x == 0):
                                    body_angle = np.abs(np.degrees(np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x)))
                                    # body_angle 是「肩→髖」向量與水平線的夾角，值域 0~180°：
                                    #   站立 → 髖在肩正下方 → 約 90°
                                    #   躺著、頭朝右 → 約 0°
                                    #   躺著、頭朝左 → 約 180°   ← 只寫 `< 40` 會整個漏掉這一半
                                    # 取 min(a, 180-a) 換算成「離水平多遠」，兩個躺向都涵蓋。
                                    # 門檻 40 沒動：頭朝右那半的判定與改動前完全相同。
                                    # 實測抓到的：手機當攝影機時量到 167~177°，體角判定形同虛設，
                                    # 全靠長寬比在撐；人朝鏡頭方向倒下（人形框不會變寬）就會漏報。
                                    tilt_from_horizontal = min(body_angle, 180.0 - body_angle)
                                    if tilt_from_horizontal < 40.0 or (w_box_i / h_box_i) > 1.25: is_lying_i = True
                            except Exception: pass

                            # 跌倒防線 B (幾何遮擋防禦)
                            if normal_h_reference is not None:
                                if (h_box_i / normal_h_reference) < 0.70 and y2 > (img_h * 0.5): is_occluded_i = True

                            person_fall_flags.append((idx, is_lying_i, is_occluded_i))
                            if is_lying_i or is_occluded_i:
                                fall_person_boxes.append((x1, y1, x2, y2))

                        # 迴圈外的兩個旗標＝逐人結果的 any()：任何一個人被判倒地就算數。
                        # 下游（AcT 幾何模擬分支、終極決策中樞、route_by_confidence 的
                        # is_occluded_fall 參數）語意不變，仍是「這一幀這台相機有沒有人倒地」。
                        is_physically_lying = any(l for _, l, _ in person_fall_flags)
                        is_occluded_fall = any(o for _, _, o in person_fall_flags)

                        # 多人時把逐人判定印出來（節流：最多每 _MULTI_LOG_MIN_GAP_SEC 一次）。
                        # 單人畫面完全不印，維持原本的 log 乾淨度；這條在現場查
                        #「到底是誰被判倒地、是不是又是最大框那位」時是唯一的線索。
                        if len(valid_idxs) > 1 and (is_physically_lying or is_occluded_fall):
                            _now_log = time.time()
                            if _now_log - _multi_log_t >= _MULTI_LOG_MIN_GAP_SEC:
                                _multi_log_t = _now_log
                                _flagged = [(i, int(l), int(o)) for i, l, o in person_fall_flags if l or o]
                                print(f"👥 [{camera_id}] 逐人幾何判定：{len(valid_idxs)} 人通過門檻，"
                                      f"best_idx={best_idx}（餵 AcT）｜判定倒地 (idx, 防線A, 防線B)={_flagged}")

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

        # 模組 G：環境安全巡檢定時器呼叫（白名單內唯一的外掛模組）
        # 第 3、4 個參數原本是模組 A 離床 / 模組 E 遊走的旗標，兩個模組已刪除故恆為 False。
        # sanity_check.py 是白名單檔、一行不動，所以維持原簽章、由呼叫端傳字面值。
        check_status = sanity_checker.process(frame, ever_detected_fall, False, False, producer)
        if check_status is not None:
            vlm_report = check_status

        # =========================================================================
        # 🚦 終極決策中樞
        # =========================================================================
        # 觸發時記兩件事：ever_detected_fall（「這一路曾經發生過」，供串流結束總結與巡檢
        # 抑制用，語意本來就是永久的）與 fall_display_until（畫面紅框要顯示到什麼時候）。
        # 兩者刻意分開：顯示要反映「現在」，而不是「歷史上曾經」。
        if should_trigger_fall:
            ever_detected_fall = True
            fall_display_until = time.time() + _FALL_DISPLAY_HOLD_SEC

        if time.time() < fall_display_until:
            status_text = "FALL DETECTED!"
            color = (0, 0, 255)

        else:
            if len(frame_window) < 30:
                status_text = "Buffering..."; color = (0, 255, 255); draw_border = False   
            else:
                status_text = "Normal"; color = (0, 255, 0)

        # =========================================================================
        # ⚡ ⚡ ⚡ 業界商用規格修改：動態不重複相片命名與傳遞 ⚡ ⚡ ⚡
        # =========================================================================
        if should_trigger_fall and not vlm_triggered:
            # 🧠 1. 解析並對齊 device_id 為 int
            try:
                numeric_id = int(''.join(filter(str.isdigit, camera_id)))
            except ValueError:
                numeric_id = 1

            # 🧠 2. 對齊事件型態字串
            # 模組 I（座椅滑落）已刪除，"chair_slip" 不再產生，這裡恆為 "fall"。
            event_label = "fall"

            # 🧠 3. 基礎 YOLO 推理數據規格化
            final_score = float(act_confidence) if act_confidence > 0 else 0.70
            yolo_thresh = 0.45

            # 🧠 4. 【生產品級核心】動態不重複檔名機制 (帶精確時間戳)
            current_time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
            snapshot_name = f"snapshot_{camera_id}_{current_time_str}.jpg"  # 不重複檔名
            snapshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
            os.makedirs(snapshot_dir, exist_ok=True)
            snapshot_full_path = os.path.join(snapshot_dir, snapshot_name)
            cv2.imwrite(snapshot_full_path, frame)  # 實體不重複存檔留存

            if producer is not None:
                vlm_triggered = True

                # 🧠 5. 事件片段：clip_path 從「影像來源本身」改指向這段前後 N 秒的影片。
                # 觸發當下就把 pre buffer 拍成快照、把路徑算好，讓 payload 立刻帶著它發出去；
                # 後段錄滿才在背景寫檔——警報不等影片（跌倒是急救場景，晚 N 秒是真的晚），
                # 護理師從收到警報到點開影片本來就不只 N 秒，檔案那時早就落地了。
                clip_name = f"clip_{camera_id}_{current_time_str}.mp4"
                clip_local_path = os.path.join(_CLIP_DIR, clip_name)
                clip_s3_key = f"{_CLIP_S3_PREFIX}/{clip_name}" if _CLIP_S3_BUCKET else None
                # 設了 bucket 才給 s3:// URI（後端只認這個）；否則退本地路徑，見檔頭說明。
                clip_path = (f"s3://{_CLIP_S3_BUCKET}/{clip_s3_key}"
                             if clip_s3_key else clip_local_path)
                pre_clip_snapshot = list(pre_clip_buffer)
                post_clip_buffer = []
                is_recording_post = True

                # 🚦 信心分流抽成 route_by_confidence()：由它決定送哪個 topic、組哪個 payload。
                # 這裡只負責算好參數、把回傳的 (topic, payload) 送出，路由決策可被 LangGraph 接管。
                topic, payload = route_by_confidence(
                    act_confidence=act_confidence,
                    is_occluded_fall=is_occluded_fall,
                    event_label=event_label,
                    numeric_id=numeric_id,
                    clip_path=clip_path,
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

            # 逐人標註：把「這一幀被判定倒地的那個人」框成紅色。多人時這是畫面上唯一
            # 能看出「系統認為是誰倒了」的資訊——.plot() 畫的框每個人都長一樣。
            # 刻意用當幀結果（不套 fall_display_until 的保持機制）：那個機制是給整張畫面的
            # 狀態燈用的，逐人框要對得上當下這一幀的骨架位置，延後顯示會框到別的地方。
            # 代價是判定逐幀跳動時紅框會閃，屬已知取捨。
            for _fx1, _fy1, _fx2, _fy2 in fall_person_boxes:
                cv2.rectangle(annotated_frame, (int(_fx1), int(_fy1)), (int(_fx2), int(_fy2)), (0, 0, 255), 3)

            if draw_border: cv2.rectangle(annotated_frame, (0, 0), (img_w, img_h), color, 12)
            cv2.putText(annotated_frame, status_text, (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3, cv2.LINE_AA)
            cv2.putText(annotated_frame, f"VLM Status: {vlm_report}", (40, img_h - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)

            if is_current_frame_valid: last_valid_annotated_frame = annotated_frame.copy()
            with frames_lock: output_frames[camera_id] = annotated_frame.copy()

            # 同一張畫好框的畫面，多送一份到 MediaMTX 的偵測頻道給前端看。
            # publish() 保證不阻塞也不拋例外：滿了就丟幀，優先保住推論的節奏。
            if detect_pub is not None:
                detect_pub.publish(annotated_frame)

        # FPS_NO_THROTTLE=1：量純 GPU 吞吐上限時，略過貼齊 source fps 的節流睡眠。
        if not _fps_no_throttle:
            t_elapsed = time.time() - t_start
            t_sleep = frame_delay - t_elapsed
            if t_sleep > 0: time.sleep(t_sleep)

    cap.release()
    if detect_pub is not None:
        detect_pub.close()

# =========================================================================
# 🏢 主執行緒專職 GUI 與排列控制
# =========================================================================
if __name__ == "__main__":
    # 💡 業界測試多路併發：可直接在此擴充相機與不同的測試影片
    # 測試影片放在 ai/test_demo/，以 __file__ 為基準解析絕對路徑，不受從哪個目錄啟動影響。
    _AI_DIR = os.path.dirname(os.path.abspath(__file__))
    _HARDCODED_CHANNELS = {
        "Room_301_Bed": os.path.join(_AI_DIR, "test_demo", "test1.mp4"),
        "Room_302_Bed": os.path.join(_AI_DIR, "test_demo", "test2.mp4"),
        "Room_303_Bed": os.path.join(_AI_DIR, "test_demo", "test3.mp4"),
    }
    # 相機清單來源開關：
    #   CAMERA_SOURCE=backend（預設）→ 啟動時打後端 GET /devices，只取 status=active 且
    #     stream_channel 非空的裝置，房號用 device_id 對齊（Room_<device_id>_Bed）。真攝影機走這條。
    #   CAMERA_SOURCE=hardcoded → 位元級沿用上面三支 mp4（沒有後端的離線 demo / 純量測用）。
    _CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "backend").strip().lower()
    if _CAMERA_SOURCE not in ("backend", "hardcoded"):
        print(f"❌ CAMERA_SOURCE={_CAMERA_SOURCE} 無效（可用值：backend / hardcoded）")
        raise SystemExit(1)

    # 下面的 SINGLE_SOURCE / STRESS_CAM_COUNT 會「整包換掉」camera_channels，此時去打後端
    # 只是白等（量測流程在後端沒開時也該能跑），直接略過抓取。RTSP_TEST_URL 是加掛一路，不算。
    _overrides_replace_all = bool(os.environ.get("SINGLE_SOURCE") or
                                  os.environ.get("STRESS_CAM_COUNT"))

    # 偵測頻道（AI 畫框後要推回去的地方）。只有 CAMERA_SOURCE=backend 這條路拿得到，
    # 因為它是資料庫欄位；離線 demo / 壓測沒有後端可問，維持不推流。
    detect_channels = {}

    if _CAMERA_SOURCE == "hardcoded" or _overrides_replace_all:
        camera_channels = dict(_HARDCODED_CHANNELS)
    else:
        try:
            # 一次登入 + 一次 GET /devices，原味與偵測兩份清單共用，不重複問後端。
            _devices = fetch_devices(login())
            camera_channels = build_camera_channels(devices=_devices)
            detect_channels = build_detect_channels(devices=_devices)
        except BackendUnavailable as e:
            print("=" * 70)
            print(f"❌ [CAMERA_SOURCE=backend] 無法從後端取得相機清單：{e}")
            print(f"   後端位址：{BACKEND_API_URL}（可用 BACKEND_API_URL 覆蓋）")
            print("   排除方式：")
            print("     1) 後端沒開 → docker compose up -d backend，再 curl 該位址的 /health")
            print("     2) 帳密沒設 → 在 repo 根目錄 .env 補 BACKEND_API_USER / BACKEND_API_PASSWORD")
            print("     3) 清單是空的 → cd backend && python -m init_db，或用 admin 打 POST /devices")
            print("        新增一台 status=active 且 stream_channel 非空的裝置")
            print("     4) 先不接後端、跑離線 demo → CAMERA_SOURCE=hardcoded python ai/inference_test.py")
            print("=" * 70)
            raise SystemExit(1)
        print(f"📡 [CAMERA_SOURCE=backend] 由後端取得 {len(camera_channels)} 路鏡頭：{camera_channels}")
        if detect_channels:
            print(f"📤 其中 {len(detect_channels)} 路有偵測頻道（畫框後推回）：{detect_channels}")
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
        # detect_channels 對不到就是 None＝這路不推流（沒設偵測頻道，或走離線 demo）。
        t = threading.Thread(target=camera_worker,
                             args=(cam_id, stream_src, detect_channels.get(cam_id)))
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
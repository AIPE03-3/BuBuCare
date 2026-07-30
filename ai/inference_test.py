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

from pose_features import (                             # AcT 34 維輸入的唯一定義
    DEFAULT_FEATURE_NORM, check_feature_norm, empty_feature, is_feature_valid, pose_feature,
)
from fall_chain import FallAlarmGate, person_geometry   # 幾何防線 A/B 與告警閘門的唯一定義
from person_tracks import PersonTrackStore, build_tracker, observe_tracks  # 多人追蹤
from av_reader import open_source, is_stream_source       # AV1 影片解碼（PyAV），介面對齊 cv2.VideoCapture
from backend_devices import (                             # 從後端裝置表取真實攝影機清單
    build_camera_channels, BackendUnavailable, BACKEND_API_URL, cfg,
)

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

# =========================================================================
# ⚠️ 潛在危險物品偵測（event_type="hazard"）
# =========================================================================
# 跟跌倒是**兩種不同形狀的事件**，別套同一套邏輯：
#   - 跌倒＝瞬間事件：有明確事發時刻，錄前後 N 秒成 clip，靠 vlm_triggered 一次性閂鎖擋重複。
#   - 危險物品＝持續狀態：刀放在桌上會「每一幀都偵測到」，且被收走後再出現應該要能再報。
#     故它沒有 clip（沒有「事發前後」可錄，只存快照），去重也不能用永不重置的閂鎖，
#     必須用「出現→確認→消失」的狀態機（見 camera_worker 內 _hazard_state）。
#
# 類別限定 COCO 80 類內真的有的東西。藥品/玻璃碎片/積水不在 COCO，得等重訓才有
# （同 wheelchair 的處境，見 triton_detr_client 檔頭）——不要先寫進來變成永不觸發的死碼。
# 熱源家電（oven/toaster/microwave）刻意不收：那是固定家電，只要在畫面裡就永遠偵測得到，
# 收了等於永久亮著的告警，要做得先設計區域白名單或時段規則。
HAZARD_CLASSES = {"knife", "scissors"}

# 三個門檻都走 cfg() 而不是 os.environ.get：專案的 .env 是用 dotenv_values 讀成 dict、
# 刻意不注入 os.environ（見 backend_devices 檔頭），只讀 os.environ 會看不到 .env 的設定。
# 這些是長期調校參數（要寫進 .env 常駐），不同於 DETR_EVERY_N/NO_RENDER 那種臨時壓測開關。
#
# 危險物品的信心門檻。比環境家具的 0.35 嚴：家具偵錯了頂多空間參考框歪一點，
# 危險物品偵錯了是直接推一則告警去吵護理師，誤報成本高得多。
HAZARD_CONF = float(cfg("HAZARD_CONF", "0.5"))
# 連續看到 N 次才確認成立（防單幀閃爍誤報）。
HAZARD_CONFIRM_FRAMES = int(cfg("HAZARD_CONFIRM_FRAMES", "5"))
# 連續 M 次沒看到才判定物品已移除（防短暫遮擋就誤判消失，導致一移開就重報）。
HAZARD_GONE_FRAMES = int(cfg("HAZARD_GONE_FRAMES", "30"))

# 「跌倒防線 B」的高度門檻：人框縮到正常身高的幾成以下，才算被家具遮擋的跌倒（見 :702）。
# 曾是寫死的 0.70，實測那個值把「彎腰撿東西」「坐下」一起吃進來——這兩種動作框會縮到
# 六~七成，跟跌倒躺平的五成以下重疊。改 0.50 後，撿東西影片的誤報幀從 195 降到 7。
# 完整量測見 docs/2026-07-29-pipeline-false-alarm-fix.md。
OCCLUDED_HEIGHT_RATIO = float(cfg("OCCLUDED_HEIGHT_RATIO", "0.50"))
# AcT 能否在幾何完全正常（沒躺平、沒遮擋）時單獨發動告警。
# 實測 AcT 在單一動作短片上會對正常走路連報數十次，關掉這條後正常動作的幀誤報率
# 從 44.7% 降到 2.0%。設 true 可回到舊行為。
ACT_ALONE_CAN_TRIGGER = cfg("ACT_ALONE_CAN_TRIGGER", "false").strip().lower() == "true"

# AcT 34 維特徵的正規化基準：image=對整張畫面（現行）／bbox=對人物框。
# ⚠ 這個值**必須跟 Triton 上那顆 AcT 訓練時用的一致**。不一致不會報錯、shape 也一樣，
# 但模型看到的是完全不同語意的向量，輸出全是垃圾。換模型時務必一起換。
# 訓練端用的模式記在 <權重>.run.json 的 feature_norm，對照那裡設。
ACT_FEATURE_NORM = check_feature_norm(cfg("ACT_FEATURE_NORM", DEFAULT_FEATURE_NORM))

# 跌倒主鏈是否追蹤畫面裡所有人。預設 false＝維持既有單人行為（只看 conf×框面積 最大者）。
#
# 為什麼需要：公共區域（客廳、走廊、餐廳）本來就有好幾個人，而單人選法永遠挑
# 「離鏡頭最近最大」的那個。實測自錄俯視影片 test6.mp4：系統全程追著站立的前景
# 路人，真正跌倒在地的人從頭到尾沒被看過一眼；開多人後 0.2 秒內就抓到。
#
# ⚠ 只影響跌倒主鏈。六大防線（離床/躁動/座椅滑落/徘徊…）仍吃「主要人物」，
#   因為那些是房間內的單人語意，公共區域本來就不該啟用。
#
# ⚠ 前提：ACT_ALONE_CAN_TRIGGER=false（現況）。此時 AcT 只在幾何已標記躺平/遮擋
#   時才被詢問，所以每幀 AcT 呼叫次數通常是 0，Triton 的 batch=1 完全夠用。
#   若哪天把 ACT_ALONE_CAN_TRIGGER 打開，就變成每個人每幀都要問 AcT，
#   N 個人＝N 趟 Triton 來回，人多會掉幀——那時要先把 AcT 重匯出成動態 batch。
ACT_MULTI_PERSON = cfg("ACT_MULTI_PERSON", "false").strip().lower() == "true"
# 告警重新武裝前要連續看到幾個處理幀「畫面上沒人躺著」。見 FallAlarmGate 的說明。
FALL_REARM_FRAMES = int(cfg("FALL_REARM_FRAMES", "15"))


def camera_numeric_id(camera_id):
    """相機代號取數字當 device_id（Room_301_Bed → 301）；取不到退 1（同原地端行為）。"""
    try:
        return int(''.join(filter(str.isdigit, camera_id)))
    except ValueError:
        return 1


def save_event_snapshot(camera_id, frame):
    """事件快照落地，回 (檔名, 完整路徑, 時間戳字串)。

    時間戳一併回傳是因為跌倒的 clip 檔名要跟快照對齊（同一起事件的兩個檔看得出是一組）。
    """
    time_str = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    name = f"snapshot_{camera_id}_{time_str}.jpg"   # 帶秒級時間戳，檔名不重複
    snapshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
    os.makedirs(snapshot_dir, exist_ok=True)
    full_path = os.path.join(snapshot_dir, name)
    cv2.imwrite(full_path, frame)
    return name, full_path, time_str


def build_hazard_payload(*, hazard_class, numeric_id, detected_at,
                         snapshot_full_path, snapshot_name, score):
    """組一則潛在危險事件，固定走快速道（processed-reports）→ 後端直接落庫。

    不做信心分流（不同於 route_by_confidence）：物件偵測是「畫面裡有沒有這個東西」的
    明確判斷，不像跌倒那樣需要 VLM 讀情境（是真跌倒還是自己蹲下）。送 VLM 二審只會
    多一層延遲跟成本，換不到任何額外資訊。

    `clip_path` 固定為 None：持續狀態沒有「事發前後 N 秒」可錄，只帶快照。後端已放寬
    此欄位為選填（僅 hazard 可空，跌倒仍強制要有，見 events/service.py）。

    `hazard_object` 直接送 COCO class name（英文），不在這裡翻中文——顯示文字是前端的事
    （前端 HAZARD_OBJECT_LABEL 負責），三層之間傳同一個 key，不做語意轉換。
    """
    return TOPIC_PROCESSED_REPORTS, {
        "device_id": numeric_id,
        "event_type": "hazard",
        "hazard_object": hazard_class,
        "clip_path": None,
        "detected_at": detected_at,
        "snapshot_path": snapshot_full_path,
        "image_filename": snapshot_name,
        "yolo_score": score,
        "vlm_summary": f"【潛在危險】偵測到 {hazard_class}，請確認是否需要移除。",
    }


def route_by_confidence(*, act_confidence, is_chair_slipped, is_occluded_fall,
                        event_label, numeric_id, clip_path, detected_at,
                        snapshot_full_path, snapshot_name, final_score, yolo_thresh):
    """依 AcT 信心把單一跌倒/滑落事件路由到對應 Kafka topic，回傳 (topic, payload)。

    這是 C 組信心分流的乾淨抽離點（原本寫死在 camera_worker 裡的 if/else）：
      - 高信心（act_confidence >= FAST_TRACK_CONF 或明確 chair_slip）且非遮擋不確定
        → (processed-reports, 快速道 payload)：後端 consumer 直接落 PostgreSQL，不經 VLM。
      - 其餘（信心不足 / 遮擋難判）
        → (nursing-home-alerts, 待審 payload)：走 Kafka → vlm_worker 二審 → 回 processed-reports。

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
    is_fast_track = (act_confidence >= FAST_TRACK_CONF or is_chair_slipped) and not is_occluded_fall

    if is_fast_track:
        # 🟢 分流 A：快速道路（Critical_Fast_Track）——高信心/明確滑落，直入後端落庫。
        # 這條直接進後端，只帶後端要的欄位；不帶 yolo_threshold（AI 內部用的門檻值）。
        payload = {
            "device_id": numeric_id,
            "event_type": event_label,
            "clip_path": str(clip_path),
            "detected_at": detected_at,
            "snapshot_path": snapshot_full_path,
            "image_filename": snapshot_name,
            "yolo_score": final_score,
            "vlm_summary": "【緊急通報】邊緣端偵測到輪椅意外滑落/嚴重跌倒！請立刻前往救援。",
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
# AWS 憑證的變數名沿用後端那組（backend/core/config.py 也是讀這兩個名字），
# 不是 boto3 標準的 AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY——故必須顯式傳進 client，
# 光靠 boto3 預設憑證鏈是抓不到的。留空則傳 None，退回預設鏈（EC2/GCP VM 的 IAM role 走這條）。
_S3_REGION = cfg("S3_REGION")
_S3_ACCESS_KEY = cfg("ACCESS_KEY_ID")
_S3_SECRET_KEY = cfg("SECRET_ACCESS_KEY")


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
        # avc1（H.264）瀏覽器 <video> 才播得動；有些 OpenCV build 沒帶 H.264 編碼器，
        # 開不起來就退 mp4v（一般播放器仍可開，只是瀏覽器相容性差）。
        writer = cv2.VideoWriter(out_path, _video_fourcc("avc1"), fps, (w, h))
        if not writer.isOpened():
            writer = cv2.VideoWriter(out_path, _video_fourcc("mp4v"), fps, (w, h))
        if not writer.isOpened():
            print(f"❌ [{camera_id}] 片段寫檔失敗：avc1 / mp4v 編碼器都開不起來 → {out_path}")
            return
        for f in frames:
            writer.write(f)
        writer.release()
        print(f"🎬 [{camera_id}] 事件片段已寫入（{len(frames)} 幀 @ {fps:.1f}fps）：{out_path}")

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
    # 多人追蹤：只在 ACT_MULTI_PERSON=true 時建立。false 時全為 None，舊路徑一行未動。
    person_tracker = build_tracker() if ACT_MULTI_PERSON else None
    person_store = PersonTrackStore(30) if ACT_MULTI_PERSON else None
    # 多人版的重複抑制。取代 vlm_triggered 的永久閂鎖——公共區域必須能報第二個人，
    # 但又不能因為追蹤 ID 換號就把同一次跌倒重複報（本專案不做身分辨識）。
    fall_gate = FallAlarmGate(FALL_REARM_FRAMES) if ACT_MULTI_PERSON else None
    processed_frame_index = 0   # 處理幀序號（給 track 的中斷偵測用，與 frame_count 解耦）
    vlm_triggered = False
    vlm_report = "Waiting for alert..."
    
    last_pose_feat = empty_feature()
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
    # 提速：NO_RENDER=1 時跳過 Step D 純畫圖渲染（.plot()/putText/copy），
    # 這些只為 GUI 顯示，HEADLESS 壓測根本不看畫面卻每幀白燒 CPU。快照存檔仍保留（事件證據）。
    _no_render = bool(os.environ.get("NO_RENDER"))
    # 提速：DETR_EVERY_N=N（N>1）把 rt_detr 環境物件偵測降頻成「每 N 個處理幀才跑一次」，
    # 其餘幀復用上次結果。detr 佔 ~30% 幀時間，但它偵測的全是靜態家具（bed/chair/couch…），
    # results_env 兩個下游用途（bed_box 離床、chair_box 座椅滑落）都只是
    #「空間參考框」，家具不會動、幾秒不更新沒差；pose 則必須每幀跑（要餵連續 30 幀給 AcT，
    # 時序不能有洞）故完全不動。未設＝1＝位元級原本的每幀行為，隨時可退回。
    _detr_every_n = max(1, int(os.environ.get("DETR_EVERY_N", "1")))
    _detr_proc_idx = 0          # 已處理幀計數（只給 detr 降頻用，與 FPS 計數解耦）
    _cached_results_env = None  # 上次 detr 結果，跳過的幀復用
    # ⚠️ 潛在危險物品狀態機：key=COCO class name，value={streak/missing/reported}。
    # 每支相機各自一份（區域獨立：A 房的刀跟 B 房的刀是兩回事）。
    _hazard_state = {}
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
                last_pose_feat = empty_feature()
                has_seen_person = False
                # 多人模式：track 全部丟掉。斷線後 BYTETracker 的編號跟斷線前沒有
                # 對應關係，留著等於把兩個不同的人接成同一條軌跡。閘門一併重新武裝，
                # 理由同上面 frame_window.clear()——時序已斷，舊狀態不再可信。
                if person_store is not None:
                    person_store.reset()
                    person_tracker = build_tracker()
                    fall_gate.reset()
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
            _detr_updated = True   # 這幀 detr 真的跑了，危險物品狀態機可以推進
        else:
            results_env = _cached_results_env
            _detr_updated = False  # 復用快取，狀態機不動（理由見下方狀態機註解）
        _detr_proc_idx += 1

        # =====================================================================
        # ⚠️ 潛在危險物品狀態機：出現 → 確認 → 報一次 → 消失 → 可再報
        # =====================================================================
        # 只在 detr 真的更新的幀推進。降頻（DETR_EVERY_N>1）時 results_env 是復用上一次的
        # 結果，每幀都算會讓 streak 用同一批偵測結果灌水，HAZARD_CONFIRM_FRAMES 就形同虛設。
        if _detr_updated and results_env is not None:
            # 這輪看到的危險物品：class name -> 最高信心。
            # 同類取最高分而非各報一則：畫面裡兩把刀，護理師要的是「這裡有刀」一則通知。
            seen_now = {}
            for box in results_env[0].boxes:
                cls_name = yolo_env_model.names[int(box.cls[0].item())]
                score = float(box.conf[0].item())
                if cls_name in HAZARD_CLASSES and score >= HAZARD_CONF:
                    seen_now[cls_name] = max(score, seen_now.get(cls_name, 0.0))

            # 1) 這輪沒看到的既有狀態：累積 missing，滿了就整筆刪除。
            #    刪除＝忘記「已報過」，所以物品被收走後再出現能重新告警（跌倒的 vlm_triggered
            #    是永不重置的閂鎖，那套在這裡會變成「一輩子只報第一把刀」）。
            for cls_name in list(_hazard_state):
                if cls_name in seen_now:
                    continue
                state = _hazard_state[cls_name]
                state["missing"] += 1
                if state["missing"] >= HAZARD_GONE_FRAMES:
                    del _hazard_state[cls_name]

            # 2) 這輪看到的：累積 streak，連續看到夠多次才確認成立、發一則。
            for cls_name, score in seen_now.items():
                state = _hazard_state.setdefault(cls_name, {"streak": 0, "missing": 0, "reported": False})
                state["streak"] += 1
                state["missing"] = 0
                if state["reported"] or state["streak"] < HAZARD_CONFIRM_FRAMES:
                    continue

                # 確認成立：標記已報，物品消失（狀態被刪）前不再重複發，避免每幀洗版。
                state["reported"] = True
                if producer is None:
                    continue
                snapshot_name, snapshot_full_path, _ = save_event_snapshot(camera_id, frame)
                topic, payload = build_hazard_payload(
                    hazard_class=cls_name,
                    numeric_id=camera_numeric_id(camera_id),
                    detected_at=datetime.now().isoformat(),  # 符合後端解析的 ISO 時間字串
                    snapshot_full_path=snapshot_full_path,
                    snapshot_name=snapshot_name,
                    score=score,
                )
                producer.send(topic, value=payload)
                producer.flush()
                print(f"⚠️ [{camera_id}] 潛在危險：偵測到 {cls_name}（信心 {score:.2f}），已通報。")

        bed_box_xyxy = None

        # 從 rt_detr 結果取床的框，交給模組 A（離床偵測）當空間參考框。
        # 座椅/沙發的框由 modules/chair_slip.py 自己從 results_env 找，這裡不重複解析。
        if results_env and len(results_env[0].boxes) > 0:
            for box in results_env[0].boxes:
                cls_id = int(box.cls[0].item())
                if yolo_env_model.names[cls_id] == "bed":
                    bed_box_xyxy = box.xyxy.cpu().numpy()[0]

        current_pose_feat = empty_feature()
        is_current_frame_valid = False
        is_physically_lying = False
        is_occluded_fall = False
        is_leaving_bed = False
        is_whitespace = False
        is_agitated = False
        is_chair_slipped = False
        observed_persons = []   # 多人模式：這一幀看到的每個人（單人模式恆為空）
        processed_frame_index += 1

        if results_pose and len(results_pose[0].keypoints) > 0:
            kpts_obj = results_pose[0].keypoints
            try:
                kpts_data = kpts_obj.xyn.cpu().numpy() 
                conf_data = results_pose[0].boxes.conf.cpu().numpy()  
                boxes_data = results_pose[0].boxes.xywh.cpu().numpy()  
                boxes_xyxy = results_pose[0].boxes.xyxy.cpu().numpy()
                # xyxyn 與 xyn 同樣對整張畫面正規化，座標系一致，bbox 正規化才算得對
                boxes_xyxyn = results_pose[0].boxes.xyxyn.cpu().numpy()

                # 多人追蹤：跌倒主鏈用它，六大防線仍走下面的「主要人物」。
                # 放在選人之前是因為它跟選人互不相干——追蹤要看所有偵測，選人只挑一個。
                if person_tracker is not None:
                    observed_persons = observe_tracks(
                        results_pose[0], person_tracker, person_store, img_h,
                        OCCLUDED_HEIGHT_RATIO, ACT_FEATURE_NORM, processed_frame_index,
                    )

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
                        temp_feat = pose_feature(kp, boxes_xyxyn[best_idx], ACT_FEATURE_NORM)
                        if is_feature_valid(temp_feat):
                            current_pose_feat = temp_feat.copy(); last_pose_feat = current_pose_feat.copy()
                            has_seen_person = True; is_current_frame_valid = True  
                        
                        _, _, w_box, h_box = boxes_data[best_idx]
                        x1, y1, x2, y2 = boxes_xyxy[best_idx]
                        if normal_h_reference is None and frame_count > 10 and frame_count < 40: normal_h_reference = h_box

                        # 跌倒防線 A（躺平）＋ B（幾何遮擋）。邏輯搬到 fall_chain.person_geometry，
                        # 本機評估與多人路徑共用同一份——寫多份的話改了一邊漏另一邊，
                        # 數字對不起來時查不出是哪邊（見 fall_chain 檔頭）。
                        # try/except 沿用原本防線 A 的寫法：幾何算不出來時不能連帶讓
                        # 下面六大防線一起被跳過（那是外層 except 的行為）。
                        try:
                            main_geometry = person_geometry(
                                kp, boxes_data[best_idx], boxes_xyxy[best_idx], img_h,
                                normal_h_reference, OCCLUDED_HEIGHT_RATIO,
                            )
                            is_physically_lying = main_geometry["is_lying"]
                            is_occluded_fall = main_geometry["is_occluded"]
                        except Exception: pass


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
        fall_person_count = 0   # 這一幀幾何判定「倒下」的人數（多人模式才會非 0）
        if ACT_MULTI_PERSON:
            # ── 多人：逐人判斷，任何一人成立就觸發 ──────────────────────────
            # AcT 只問「幾何已經標記躺平/遮擋」的人。ACT_ALONE_CAN_TRIGGER=false 時
            # 幾何正常者的 AcT 結果根本不會被採用（見下面的判斷式），問了純浪費一趟
            # Triton 來回。實務上每幀通常 0 人需要問，比單人版的每幀 1 次還省。
            for track, geometry, _ in observed_persons:
                if not track.has_seen:
                    continue
                geometry_hit = geometry["is_lying"] or geometry["is_occluded"]
                if geometry_hit:
                    fall_person_count += 1
                if not (geometry_hit or ACT_ALONE_CAN_TRIGGER):
                    continue

                window_ready = track.window_full
                person_pred, person_conf = 1, 0.0
                if window_ready and transformer_model is not None:
                    try:
                        person_logits = transformer_model(track.window_array()[0])
                        person_prob = torch.softmax(
                            torch.from_numpy(np.asarray(person_logits, dtype=np.float32)), dim=1)
                        person_pred = torch.argmax(person_prob, dim=1).item()
                        person_conf = person_prob[0][person_pred].item()
                    except Exception as e:
                        # 與單人版同樣的 Triton 斷線降級：退回幾何模擬，不讓 worker 崩
                        if not triton_down_warned:
                            print(f"⚠️ [{camera_id}] Triton AcT 推論失敗（降級：退回幾何模擬判斷）：{e}")
                            triton_down_warned = True
                        person_pred = 0 if geometry["is_lying"] else 1
                        person_conf = 0.75 if geometry["is_lying"] else 0.0
                elif window_ready:
                    person_pred = 0 if geometry["is_lying"] else 1
                    person_conf = 0.75 if geometry["is_lying"] else 0.0
                person_thinks_fall = window_ready and person_pred == 0 and person_conf > 0.35

                # 觸發條件與單人版逐項對齊（:769-771），只是把「那個人」換成「這個人」
                person_trigger = False
                if geometry_hit:
                    if not window_ready or person_thinks_fall or geometry["is_occluded"]:
                        person_trigger = True
                elif ACT_ALONE_CAN_TRIGGER and window_ready and person_pred == 0 and person_conf > 0.55:
                    person_trigger = True

                if person_trigger:
                    track.latched = True
                    should_trigger_fall = True
                    # 對外回報的信心值取「最像跌倒的那個人」——payload 只有一個欄位
                    if person_conf > act_confidence:
                        act_confidence = person_conf
                        pred_class = person_pred
        elif has_seen_person:
            if is_physically_lying or is_occluded_fall:
                if len(frame_window) < 30 or is_ai_thinking_fall or is_occluded_fall: should_trigger_fall = True
            # 幾何正常時 AcT 單獨發動：預設關閉，理由見 ACT_ALONE_CAN_TRIGGER 的註解。
            elif ACT_ALONE_CAN_TRIGGER and len(frame_window) == 30 and pred_class == 0 and act_confidence > 0.55: should_trigger_fall = True

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

        # 多人模式的發報閘門。**必須每個處理幀呼叫一次**，重新武裝靠連續計數。
        # 單人模式不呼叫，維持原本的 vlm_triggered 永久閂鎖。
        fall_alarm_allowed = (fall_gate.update(should_trigger_fall, fall_person_count > 0)
                              if fall_gate is not None else False)

        # =========================================================================
        # 🚦 終極決策中樞
        # =========================================================================
        # 畫面狀態：單人模式沿用 ever_detected_fall（觸發後永久紅）。多人模式改看
        # 「現在還有沒有人倒著」——公共區域 24 小時在跑，畫面永久停在紅色，
        # 值班人員第二次跌倒時根本分不出是新事件還是舊的殘留。
        fall_display_active = (fall_person_count > 0) if ACT_MULTI_PERSON else ever_detected_fall
        if should_trigger_fall or fall_display_active or is_chair_slipped:
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
        # 發報條件。單人模式：一次性閂鎖（報過就永遠不再報）。
        # 多人模式：跌倒走邊緣觸發閘門（地上淨空後可再報下一個人），座椅滑落仍走
        # 原本的閂鎖——那是單人語意的防線，不在本次多人化範圍內。
        if ACT_MULTI_PERSON:
            fall_alert_now = fall_alarm_allowed or (is_chair_slipped and not vlm_triggered)
        else:
            fall_alert_now = (should_trigger_fall or is_chair_slipped) and not vlm_triggered
        if fall_alert_now:
            # 🧠 1. 解析並對齊 device_id 為 int
            numeric_id = camera_numeric_id(camera_id)

            # 🧠 2. 對齊事件型態字串
            event_label = "chair_slip" if is_chair_slipped else "fall"

            # 🧠 3. 基礎 YOLO 推理數據規格化
            final_score = float(act_confidence) if act_confidence > 0 else 0.70
            yolo_thresh = 0.45 if event_label == "fall" else 0.35

            # 🧠 4. 【生產品級核心】動態不重複檔名機制 (帶精確時間戳)
            snapshot_name, snapshot_full_path, current_time_str = save_event_snapshot(camera_id, frame)

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
                    is_chair_slipped=is_chair_slipped,
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

        # === Step D: 畫布渲染（骨架框 + 狀態文字） ===
        # NO_RENDER=1（HEADLESS 壓測）：整段純畫圖只為 GUI 顯示，跳過以省 CPU；偵測/外發/快照不受影響。
        # 註：環境物件不疊圖。rt_detr 無分割頭（triton_detr_client 恆回 masks=None），
        #     要疊只能改畫 boxes；YOLO-Seg 時代的輪廓疊圖已移除。
        if not _no_render:
            annotated_frame = results_pose[0].plot(boxes=True, labels=True, conf=0.45)

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
    _HARDCODED_CHANNELS = {
        "Room_301_Bed": os.path.join(_AI_DIR, "test_demo", "test1.mp4"),
        "Room_302_Bed": os.path.join(_AI_DIR, "test_demo", "test2.mp4"),
        "Room_303_Bed": os.path.join(_AI_DIR, "test_demo", "test3.mp4"),
    }
    # 相機清單來源開關：
    #   CAMERA_SOURCE=backend（預設）→ 啟動時打後端 GET /devices，只取 status=active 且
    #     stream_url 非空的裝置，房號用 device_id 對齊（Room_<device_id>_Bed）。真攝影機走這條。
    #   CAMERA_SOURCE=hardcoded → 位元級沿用上面三支 mp4（沒有後端的離線 demo / 純量測用）。
    _CAMERA_SOURCE = os.environ.get("CAMERA_SOURCE", "backend").strip().lower()
    if _CAMERA_SOURCE not in ("backend", "hardcoded"):
        print(f"❌ CAMERA_SOURCE={_CAMERA_SOURCE} 無效（可用值：backend / hardcoded）")
        raise SystemExit(1)

    # 下面的 SINGLE_SOURCE / STRESS_CAM_COUNT 會「整包換掉」camera_channels，此時去打後端
    # 只是白等（量測流程在後端沒開時也該能跑），直接略過抓取。RTSP_TEST_URL 是加掛一路，不算。
    _overrides_replace_all = bool(os.environ.get("SINGLE_SOURCE") or
                                  os.environ.get("STRESS_CAM_COUNT"))

    if _CAMERA_SOURCE == "hardcoded" or _overrides_replace_all:
        camera_channels = dict(_HARDCODED_CHANNELS)
    else:
        try:
            camera_channels = build_camera_channels()
        except BackendUnavailable as e:
            print("=" * 70)
            print(f"❌ [CAMERA_SOURCE=backend] 無法從後端取得相機清單：{e}")
            print(f"   後端位址：{BACKEND_API_URL}（可用 BACKEND_API_URL 覆蓋）")
            print("   排除方式：")
            print("     1) 後端沒開 → docker compose up -d backend，再 curl 該位址的 /health")
            print("     2) 帳密沒設 → 在 repo 根目錄 .env 補 BACKEND_API_USER / BACKEND_API_PASSWORD")
            print("     3) 清單是空的 → cd backend && python -m init_db，或用 admin 打 POST /devices")
            print("        新增一台 status=active 且 stream_url 非空的裝置")
            print("     4) 先不接後端、跑離線 demo → CAMERA_SOURCE=hardcoded python ai/inference_test.py")
            print("=" * 70)
            raise SystemExit(1)
        print(f"📡 [CAMERA_SOURCE=backend] 由後端取得 {len(camera_channels)} 路鏡頭：{camera_channels}")
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
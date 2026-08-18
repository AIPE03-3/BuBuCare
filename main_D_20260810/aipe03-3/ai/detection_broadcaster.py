"""把每幀的人體框與骨架座標推給後端，前端 canvas 疊在乾淨影像上畫。

取代 `ai/detect_publisher.py`（2026-07-31 移除）。兩者要解的是同一個問題——
「前端切到偵測模式時要看得到 AI 畫的骨架」——差別在疊圖發生的位置：

    detect_publisher（舊）  AI 把框燒進畫面 → 再編一次 H.264 → 推 MediaMTX cam_out
    本檔（新）              AI 只送座標 JSON → 後端轉播 → 瀏覽器 canvas 疊在 cam_in 上

換過來的三個理由：

1. **AI 端省掉一整條 H.264 編碼**。舊做法每路相機多開一支 ffmpeg 子程序做即時編碼，
   那是推論主迴圈以外最貴的一件事；現在只剩一次幾 KB 的 HTTP POST。
2. **前端可以隨手關掉骨架**。值班人員要看清楚長輩的臉時，框燒在畫面裡就拿不掉了。
3. **頻寬與延遲**：座標 JSON 比第二條 720p 影像串流小三個數量級，而且不必等編碼。

代價（要知道）：框不在影像裡，所以**用 VLC 之類的外部播放器看 MediaMTX 就沒有框**。
舊做法看得到。組內決策是前端值班畫面優先，接受這個代價。

## 設計取捨（沿用 detect_publisher 定下的四條，一條都沒放寬）

1. **滿了就丟幀，絕不阻塞推論迴圈。** 轉播是「看畫面」的附加功能，跌倒偵測才是主線。
   有界佇列 + 背景執行緒，佇列滿了丟最舊的那幀。即時畫面本來就該丟舊幀。
2. **任何失敗都不得往上拋。** 後端沒開、網路斷掉，最多就是前端看不到骨架，
   不該讓相機 worker 掛掉、更不該影響已經發出去的警報。
3. **不重試到洗版。** 連不上時指數退避到 30 秒封頂，而且只在「狀態翻轉」時印訊息。
4. **預設關閉**，行為與加這支之前位元級相同。要開就設 `DETECT_BROADCAST=1`。

## 座標一律正規化

送出去的 bbox 與關節點都是 0..1 的比例值，不是像素。前端的 `<video>` 會被 CSS 縮放成
任意大小，canvas 拿到像素座標就得先知道原始解析度才畫得對。
（上游 albert 的版本在這裡自相矛盾：型別註解寫「像素座標」，畫的時候卻當比例用，
換一台不同解析度的鏡頭就會畫歪。）
"""

import json
import queue
import threading
import time
import urllib.error
import urllib.request

from backend_devices import cfg

# 未設＝不轉播，行為與加這支之前位元級相同。要開就設 DETECT_BROADCAST=1。
BROADCAST_ENABLED = cfg("DETECT_BROADCAST", "").strip().lower() in ("1", "true", "yes", "on")

BACKEND_URL = cfg("BACKEND_API_URL", "http://127.0.0.1:8000").rstrip("/")
ENDPOINT = f"{BACKEND_URL}/streams/detections"
# 與 POST /events 同一把 key。刻意不另開一把：AI 端本來就帶著它在發跌倒事件。
API_KEY = cfg("EVENT_API_KEY", "")

# 每 N 個處理幀送一次。骨架是拿來「看」的，30fps 全送只是讓後端與瀏覽器多做工——
# 人眼看 10~15fps 的骨架已經很順。設 1＝每幀都送。
BROADCAST_EVERY_N = max(1, int(cfg("DETECT_BROADCAST_EVERY_N", "2")))
# 佇列深度。3 幀約 0.3 秒，落後超過這個量的座標畫上去只會對不上影像。
QUEUE_MAXSIZE = 3
HTTP_TIMEOUT = float(cfg("DETECT_BROADCAST_TIMEOUT", "1.0"))

_BACKOFF_START = 1.0
_BACKOFF_MAX = 30.0


class DetectionBroadcaster:
    """一路相機一個實例。`publish()` 保證不阻塞、不拋例外。"""

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        # 前端要靠 device_id 把座標對回它清單裡的那台鏡頭。用**與 Kafka 事件完全相同**
        # 的換算（inference_test.py 發事件時也是挖出 camera_id 裡的所有數字），
        # 前端就不必知道 "Room_301_Bed" 這個字串格式——那是 AI 端內部的命名。
        try:
            self.device_id = int("".join(filter(str.isdigit, camera_id)))
        except ValueError:
            self.device_id = 1
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
        self._stop = threading.Event()
        self._seq = 0
        self._calls = 0
        # 連線狀態：只在翻轉時印訊息，不是每次失敗都印（否則後端沒開就洗版）
        self._healthy = True
        self._backoff = _BACKOFF_START
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name=f"detect-broadcast-{camera_id}")
        self._thread.start()

    # ── 推論迴圈呼叫的唯一入口 ──────────────────────────────────────────────
    def publish(self, persons: list[dict]) -> None:
        """把這一幀的人物清單排進佇列。滿了就丟最舊的，絕不等待。"""
        self._calls += 1
        if self._calls % BROADCAST_EVERY_N:
            return
        self._seq += 1
        payload = {"device_id": self.device_id, "camera_id": self.camera_id,
                   "persons": persons, "seq": self._seq}
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            # 丟最舊的再放新的。get_nowait 可能剛被背景執行緒取走，所以要包起來。
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                pass   # 極端競態下仍然滿的：放棄這一幀，不阻塞

    def close(self) -> None:
        self._stop.set()

    # ── 背景執行緒 ──────────────────────────────────────────────────────────
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                payload = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._post(payload)

    def _post(self, payload: dict) -> None:
        req = urllib.request.Request(
            ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT):
                pass
        except Exception as e:
            self._on_failure(e)
            return
        if not self._healthy:
            print(f"✅ [{self.camera_id}] 偵測座標轉播已恢復")
        self._healthy = True
        self._backoff = _BACKOFF_START

    def _on_failure(self, err: Exception) -> None:
        if self._healthy:
            # 401 幾乎一定是 EVENT_API_KEY 沒對上，講清楚免得有人去查網路
            hint = ""
            if isinstance(err, urllib.error.HTTPError) and err.code == 401:
                hint = "（X-API-Key 與後端的 EVENT_API_KEY 對不上）"
            print(f"⚠️ [{self.camera_id}] 偵測座標轉播失敗{hint}：{err}"
                  f" —— 影像與跌倒偵測不受影響，前端只是看不到骨架")
        self._healthy = False
        # 退避期間把積壓的座標清掉：等後端回來時，舊座標對不上當下的影像了
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._stop.wait(self._backoff)
        self._backoff = min(self._backoff * 2, _BACKOFF_MAX)


def make_broadcaster(camera_id: str) -> "DetectionBroadcaster | None":
    """沒開啟或缺 API key 時回 None，呼叫端就整段跳過。"""
    if not BROADCAST_ENABLED:
        return None
    if not API_KEY:
        print(f"⚠️ [{camera_id}] DETECT_BROADCAST=1 但沒有 EVENT_API_KEY，不啟用座標轉播")
        return None
    print(f"📡 [{camera_id}] 偵測座標轉播已啟用 ➔ {ENDPOINT}"
          f"（每 {BROADCAST_EVERY_N} 幀一次）")
    return DetectionBroadcaster(camera_id)


def build_persons(*, boxes_xyxy, conf_data, kpts_xyn, fall_flags,
                  idx_to_track, img_w: int, img_h: int) -> list[dict]:
    """把這一幀的推論結果整理成後端 `DetectionFrame.persons` 的格式。

    `kpts_xyn` 已經是正規化的（ultralytics 的 `.xyn`），`boxes_xyxy` 是像素，
    所以只有框需要除以畫面尺寸。`fall_flags` 是 `person_fall_flags`
    ——元素 `(idx, is_lying, is_occluded)`，判定條件與畫面上那個紅框**同一個**
    （`is_lying or is_occluded`），不另外定義一套，免得畫面說跌倒、前端說沒有。
    """
    fall_by_idx = {idx: (lying or occluded) for idx, lying, occluded in fall_flags}
    persons = []
    for idx in sorted(fall_by_idx):
        if idx >= len(boxes_xyxy):
            continue
        x1, y1, x2, y2 = (float(v) for v in boxes_xyxy[idx])
        kps = None
        if kpts_xyn is not None and idx < len(kpts_xyn):
            # 只取前 17 點的 (x, y)；沒偵測到的關節點是 [0, 0]，前端會跳過不畫
            kps = [[round(float(x), 4), round(float(y), 4)]
                   for x, y in kpts_xyn[idx][:17, :2]]
        persons.append({
            "bbox": [round(x1 / img_w, 4), round(y1 / img_h, 4),
                     round(x2 / img_w, 4), round(y2 / img_h, 4)],
            "conf": round(float(conf_data[idx]), 4) if idx < len(conf_data) else 0.0,
            "is_fall": bool(fall_by_idx[idx]),
            "track_id": idx_to_track.get(idx),
            "kps": kps,
        })
    return persons

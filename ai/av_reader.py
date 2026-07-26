"""AV1 影片解碼 helper —— 介面對齊 `cv2.VideoCapture`，讓 inference_test.py 幾乎不用改。

背景：`ai/test_demo/*.mp4` 是 AV1 編碼。本機 opencv 5.0.0 雖 build 有 FFMPEG=YES，實測
`cv2.VideoCapture(av1.mp4)` 仍 `isOpened()==False`（其 ffmpeg 後端不含 av1 解碼器）。
PyAV 自帶 libdav1d，可解 AV1，故改用 PyAV 讀格 → 轉 numpy BGR。

`AVFrameReader` 刻意把方法命名與回傳對齊 `cv2.VideoCapture`（`isOpened` / `read` / `get`
/ `release`），這樣 camera_worker 只把建構那一行換成 `open_source(...)`，下游
`cap.get(cv2.CAP_PROP_FPS)` / `cap.read()` / `cap.release()` 一行都不用改。

執行緒注意：PyAV 的 container 與 `decode()` 迭代器綁在「建立它的執行緒」。
inference_test.py 每支相機一條 camera_worker，各自 `open_source()` 建自己的 reader，
天然每執行緒獨立、不跨執行緒共用，安全（與三顆 Triton client 的 thread-local 精神一致）。
"""
import cv2
import numpy as np

try:
    import av  # PyAV：自帶 libdav1d，可解 AV1
except ImportError:  # pragma: no cover - av 缺席時給明確指引
    av = None


class AVFrameReader:
    """用 PyAV 逐幀解碼影片，介面比照 `cv2.VideoCapture`（回 BGR numpy）。"""

    def __init__(self, path: str):
        self._path = path
        self._container = None
        self._stream = None
        self._frames = None  # decode() 迭代器（綁在建立它的執行緒）
        if av is None:
            print("❌ [AVFrameReader] 未安裝 PyAV，無法解 AV1。請執行：ai/.venv/bin/pip install av")
            return
        try:
            self._container = av.open(path)
            self._stream = self._container.streams.video[0]
            # 只要能解第一幀的執行緒，就在該執行緒建立迭代器（延遲到 read 也可，這裡先建）。
            self._frames = self._container.decode(video=0)
        except Exception as e:
            print(f"❌ [AVFrameReader] 開啟影像源失敗 {path}: {e}")
            self._container = None

    def isOpened(self) -> bool:
        return self._container is not None and self._frames is not None

    def read(self):
        """回 `(ret, frame)`，frame 為 BGR numpy（對齊 cv2.VideoCapture.read）。"""
        if not self.isOpened():
            return False, None
        try:
            frame = next(self._frames)
        except StopIteration:
            return False, None
        except Exception as e:
            print(f"⚠️ [AVFrameReader] 解碼中斷 {self._path}: {e}")
            return False, None
        return True, frame.to_ndarray(format="bgr24")

    def get(self, prop_id):
        """支援 camera_worker 用到的 CAP_PROP_FPS；其餘回 0.0（對齊 cv2 未知屬性語意）。"""
        if prop_id == cv2.CAP_PROP_FPS:
            rate = self._stream.average_rate if self._stream is not None else None
            return float(rate) if rate else 0.0
        return 0.0

    def release(self):
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
            self._frames = None


# RTSP/即時串流連續解碼失敗達此門檻，才視為上游斷流、回 (False, None) 讓 camera_worker 收尾。
# 即時流偶發封包錯很正常（尤其 mediamtx 循環影片的接縫處），故先容忍續讀、不因一兩幀壞就收工。
_STREAM_MAX_CONSEC_FAIL = 30


class AVStreamReader:
    """用 PyAV 拉 RTSP/即時串流，介面比照 `cv2.VideoCapture`（回 BGR numpy）。

    與 `AVFrameReader`（讀影片檔）的關鍵差異在「即時流特性」：
    - 建構時傳**低延遲拉流參數**給 `av.open`（對齊 Albert 舊 GStreamer `latency=100` 的意圖）：
      走 TCP 傳輸避免 UDP 掉包、關 buffer、低延遲旗標。
    - `read()` 對**暫時性**解碼錯誤容忍（續讀下一幀），只有連續失敗達 `_STREAM_MAX_CONSEC_FAIL`
      才判定斷流回 `(False, None)`；影片檔版則一遇錯就收尾。

    執行緒注意事項同 `AVFrameReader`：container / `decode()` 迭代器綁「建立它的執行緒」，
    每支相機一條 camera_worker 各自 `open_source()` 建自己的 reader，天然每執行緒獨立。
    """

    # PyAV 透傳給底層 FFmpeg 的拉流 options（RTSP demuxer 讀得懂）。
    _OPEN_OPTIONS = {
        "rtsp_transport": "tcp",   # 走 TCP，避免 UDP 掉包造成畫面破圖
        "fflags": "nobuffer",      # 不做輸入緩衝，降低延遲
        "flags": "low_delay",      # 解碼器低延遲模式
        "max_delay": "500000",     # 最大解封裝延遲 0.5s（微秒）
    }

    def __init__(self, url: str):
        self._url = url
        self._container = None
        self._stream = None
        self._frames = None
        self._consec_fail = 0
        if av is None:
            print("❌ [AVStreamReader] 未安裝 PyAV，無法拉 RTSP。請執行：ai/.venv/bin/pip install av")
            return
        try:
            # timeout：建連/讀取逾時保護，避免上游沒開時卡死（PyAV 以秒計）。
            self._container = av.open(url, options=self._OPEN_OPTIONS, timeout=10)
            self._stream = self._container.streams.video[0]
            self._frames = self._container.decode(video=0)
        except Exception as e:
            print(f"❌ [AVStreamReader] 開啟串流失敗 {url}: {e}")
            self._container = None

    def isOpened(self) -> bool:
        return self._container is not None and self._frames is not None

    def read(self):
        """回 `(ret, frame)`，frame 為 BGR numpy（對齊 cv2.VideoCapture.read）。

        暫時性解碼錯誤（單幀壞封包）續讀下一幀；連續失敗達門檻才判定斷流回 `(False, None)`。
        """
        if not self.isOpened():
            return False, None
        while self._consec_fail < _STREAM_MAX_CONSEC_FAIL:
            try:
                frame = next(self._frames)
            except StopIteration:
                # 即時流理論上不該自然結束；視為斷流收尾。
                return False, None
            except Exception as e:
                self._consec_fail += 1
                if self._consec_fail == 1:  # 只在首次失敗印一次，避免刷屏
                    print(f"⚠️ [AVStreamReader] 解碼暫時性錯誤（續讀）{self._url}: {e}")
                continue
            self._consec_fail = 0
            return True, frame.to_ndarray(format="bgr24")
        # 連續失敗過門檻 → 判定上游斷流
        print(f"⚠️ [AVStreamReader] 連續 {_STREAM_MAX_CONSEC_FAIL} 幀解碼失敗，判定斷流 {self._url}")
        return False, None

    def get(self, prop_id):
        """支援 camera_worker 用到的 CAP_PROP_FPS；其餘回 0.0（對齊 cv2 未知屬性語意）。

        即時流的 `average_rate` 可能為 None，此時回 0.0，camera_worker 已有 `fps<=0 → 30.0` 兜底。
        """
        if prop_id == cv2.CAP_PROP_FPS:
            rate = self._stream.average_rate if self._stream is not None else None
            return float(rate) if rate else 0.0
        return 0.0

    def release(self):
        if self._container is not None:
            try:
                self._container.close()
            except Exception:
                pass
            self._container = None
            self._frames = None


# 判定為「即時串流 URL」的協定前綴（走 AVStreamReader 低延遲拉流）。
_STREAM_PREFIXES = ("rtsp://", "rtp://", "rtmp://", "http://", "https://")


def open_source(video_source):
    """依影像源型別選 reader：

    - webcam index（int）：走原本的 `cv2.VideoCapture`。
    - 即時串流 URL（`rtsp://` / `rtp://` / `rtmp://` / `http(s)://`）：走 `AVStreamReader`
      （PyAV 低延遲拉流；本機 opencv `build GStreamer: NO`，故不走 cv2 GStreamer 管線）。
    - 其餘影片檔路徑（str）：走 `AVFrameReader`（PyAV，能解 AV1）。

    回傳物件都具備相同的 `isOpened / read / get / release` 介面，故 camera_worker
    只需把 `cv2.VideoCapture(video_source)` 換成 `open_source(video_source)`。
    """
    if isinstance(video_source, int):
        return cv2.VideoCapture(video_source)
    s = str(video_source)
    if s.startswith(_STREAM_PREFIXES):
        return AVStreamReader(s)
    return AVFrameReader(s)

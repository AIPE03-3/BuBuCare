"""多人追蹤的每人狀態。

## 為什麼需要這個

原本每台相機的判斷狀態是**一組單人變數**：一個 30 幀視窗、一個身高基準、
一個告警閂鎖。多人時靠 `select_main_person()`（信心 × 框面積）挑一個塞進去。

那個漏斗有兩個致命問題：

1. **選中的人會在幀之間跳**。前景路人一擋，主要人物就換人，30 幀視窗裡
   混著兩個人的骨架——那個視窗的 AcT 輸入沒有任何意義。
2. **離鏡頭最近的人永遠勝出**，但出事的往往是遠處那個。實測 test6.mp4：
   系統全程追著站立的前景路人，真正跌倒在地的人從頭到尾沒被看過一眼。

所以解法不是「把漏斗拿掉」——那只會讓所有人的骨架混進同一個視窗。
解法是把單例狀態換成**每人一份**，「主要人物切換」這個特殊情況就從程式裡
消失了，不是靠 if 擋掉。

## 追蹤器

用 ultralytics 內建的 BYTETracker（相依 `lap`），不引入新框架。
它吃 `result.boxes`、回傳 `[x1,y1,x2,y2, track_id, score, cls, det_idx]`，
最後那個 `det_idx` 是關鍵：靠它把 track_id 對回同一個人的關鍵點。
"""

from collections import deque
from types import SimpleNamespace

import numpy as np

from pose_features import empty_feature

# BYTETracker 參數。沿用 ultralytics bytetrack.yaml 的預設值，只調 track_buffer：
# 長照場景人會被家具、其他人短暫遮住，緩衝短了會頻繁換 ID，一換 ID 視窗就重來
TRACKER_ARGS = SimpleNamespace(
    tracker_type="bytetrack",
    track_high_thresh=0.25,
    track_low_thresh=0.1,
    new_track_thresh=0.25,
    track_buffer=60,
    match_thresh=0.8,
    fuse_score=True,
)

# 連續幾個處理幀沒看到就回收這個 track。10 幀 ≈ 1 秒（20fps 跳幀 2）
MAX_MISSING_FRAMES = 10
# 中斷超過這麼多處理幀才回來，視窗直接清空重來。
# 不清的話 deque 會把中斷前後的姿態接在一起，變成一段「瞬間移動」的假動作
WINDOW_RESET_GAP = 3
# 身高基準取前幾個「非躺平」樣本的中位數。
# 用中位數而非單一幀：單幀可能剛好在跨步或彎腰，中位數穩得多
HEIGHT_REF_SAMPLES = 10


def build_tracker():
    """建一個 BYTETracker。相依 `lap`，缺了給明確指示而不是丟 ImportError 堆疊。"""
    try:
        from ultralytics.trackers.byte_tracker import BYTETracker
    except ImportError as error:
        raise ImportError(
            "多人追蹤需要 lap 套件：\n"
            "    uv pip install --python ai/.venv/bin/python 'lap>=0.5.12'"
        ) from error
    return BYTETracker(TRACKER_ARGS)


class PersonTrack:
    """一個人的完整判斷狀態——單人版那組全域變數的每人副本。"""

    def __init__(self, track_id, window_size):
        self.track_id = int(track_id)
        self.window_size = window_size
        self.window = deque(maxlen=window_size)
        self.has_seen = False
        self.height_reference = None
        self.latched = False
        self.missing_frames = 0
        self.last_frame_index = None
        self._height_samples = []

    def observe(self, feature, box_height, is_lying, frame_index, valid):
        """收一幀觀測。中斷太久會先清空視窗（見 WINDOW_RESET_GAP）。"""
        if (self.last_frame_index is not None
                and frame_index - self.last_frame_index > WINDOW_RESET_GAP):
            self.window.clear()
        self.last_frame_index = frame_index
        self.missing_frames = 0

        self.window.append(feature if valid else empty_feature())
        if valid:
            self.has_seen = True
        # 身高基準只收「站著」的樣本。單人版是取前 5~20 個處理幀，不管姿勢——
        # 那在多人場景會壞掉：有人一進畫面就是躺著的，拿躺著的框高當基準，
        # 遮擋防線（h / normal_h）等於永遠不會成立
        if (self.height_reference is None and valid and not is_lying
                and box_height and box_height > 0):
            self._height_samples.append(float(box_height))
            if len(self._height_samples) >= HEIGHT_REF_SAMPLES:
                self.height_reference = float(np.median(self._height_samples))

    def mark_missing(self):
        """這幀沒看到這個人。回傳是否該回收。"""
        self.missing_frames += 1
        return self.missing_frames > MAX_MISSING_FRAMES

    @property
    def window_full(self):
        return len(self.window) == self.window_size

    def window_array(self):
        """回傳 (1, window_size, 34) 的批次輸入。視窗未滿時回 None。"""
        if not self.window_full:
            return None
        return np.asarray(self.window, dtype=np.float32)[None]


class PersonTrackStore:
    """track_id → PersonTrack 的集合，負責建立、更新與回收。"""

    def __init__(self, window_size):
        self.window_size = window_size
        self.tracks = {}

    def update(self, observations, frame_index):
        """套用這一幀的觀測，回收失聯太久的 track。

        observations: {track_id: dict(feature, box_height, is_lying, valid)}
        回傳這一幀有被看到的 PersonTrack 清單（依 track_id 排序，輸出才穩定）。
        """
        seen = []
        for track_id, observation in observations.items():
            track = self.tracks.get(track_id)
            if track is None:
                track = PersonTrack(track_id, self.window_size)
                self.tracks[track_id] = track
            track.observe(observation["feature"], observation["box_height"],
                          observation["is_lying"], frame_index, observation["valid"])
            seen.append(track)

        for track_id in [t for t in self.tracks if t not in observations]:
            if self.tracks[track_id].mark_missing():
                del self.tracks[track_id]

        return sorted(seen, key=lambda track: track.track_id)

    def reset(self):
        """畫面切換時整批丟掉——新場景的 track_id 跟舊場景沒有對應關係。"""
        self.tracks.clear()

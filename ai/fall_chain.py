"""跌倒判斷主鏈的共用邏輯：幾何防線 A/B，以及告警的重複抑制。

## 為什麼要獨立成一個模組

躺平判斷（防線 A）原本在三個地方各寫一份：

| 位置 | 角色 |
|---|---|
| `inference_test.py:713-719` | 正式推論管線 |
| `local_pipeline_eval.py` | 本機評估（訓練特徵抽取也走這裡） |
| `local_pose_eval.py:141` | 姿態診斷工具 |

跟 34 維特徵一樣的老問題：改一份漏一份，兩邊數字對不起來時查不出是哪邊。
接多人追蹤時如果再為多人路徑寫第四份，等於重犯剛修掉的錯。

所以幾何判斷只留這一份。多人與單人、正式端與本機端，全部呼叫同一個函式。

## 為什麼告警閘門也放這裡

「什麼情況算跌倒」跟「跌倒了要不要發報」是兩件事，但它們共用同一份狀態
（誰躺著、躺了多久）。放在一起比散在呼叫端清楚。
"""

import numpy as np

# 以下常數全部對齊 inference_test.py，改任何一個都會讓本機結果套不回正式管線
LYING_ANGLE_DEG = 40.0       # :718
LYING_ASPECT_RATIO = 1.25    # :718
OCCLUDED_Y2_RATIO = 0.5      # :723 —— 人框底緣要低於畫面中線才算「倒在遮蔽物後」

# COCO 關鍵點索引
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12


def person_geometry(keypoints, box_xywh, box_xyxy=None, image_height=0,
                    height_reference=None, occluded_height_ratio=0.0):
    """單一人物的幾何判斷：躺平（防線 A）、遮擋（防線 B）、軀幹角、寬高比。

    keypoints: 這個人的 `xyn` 關鍵點（對整張畫面正規化）。
    box_xywh: 同一個人的框（cx, cy, w, h），畫面像素座標。防線 A 只需要這個。
    height_reference: 這個人**站立時**的框高。多人模式下每個 track 各有一份
        （見 person_tracks.PersonTrack）；單人模式沿用全域那一個。
        為 None 時防線 B 整段跳過——沒有基準就無從判斷「變矮」，
        此時 `box_xyxy` / `image_height` / `occluded_height_ratio` 都不會被讀。
        只想要防線 A（例如姿態診斷工具）就只傳前兩個參數。

    回傳 dict，鍵名與正式管線的變數同名，對照時不必換腦袋。
    """
    result = {"is_lying": False, "is_occluded": False, "body_angle": None,
              "aspect_ratio": 0.0, "height_ratio": None, "y2_ratio": 0.0}

    _, _, box_width, box_height = box_xywh
    aspect_ratio = float(box_width / box_height) if box_height else 0.0
    result["aspect_ratio"] = aspect_ratio

    # 防線 A：軀幹接近水平，或人框變成寬扁形
    shoulder_x = (keypoints[LEFT_SHOULDER][0] + keypoints[RIGHT_SHOULDER][0]) / 2.0
    shoulder_y = (keypoints[LEFT_SHOULDER][1] + keypoints[RIGHT_SHOULDER][1]) / 2.0
    hip_x = (keypoints[LEFT_HIP][0] + keypoints[RIGHT_HIP][0]) / 2.0
    hip_y = (keypoints[LEFT_HIP][1] + keypoints[RIGHT_HIP][1]) / 2.0
    if shoulder_x != 0 and hip_x != 0:  # xyn 為 0 代表該點沒抓到，不是「在畫面左上角」
        angle = float(np.abs(np.degrees(np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x))))
        result["body_angle"] = angle
        if angle < LYING_ANGLE_DEG:
            result["is_lying"] = True
    if aspect_ratio > LYING_ASPECT_RATIO:
        result["is_lying"] = True

    # 防線 B：人突然「變矮」且位置偏下 → 可能倒在家具後面
    if height_reference is not None and box_xyxy is not None:
        _, _, _, y2 = box_xyxy
        # 原始數值一併留下，讓離線掃描能重算不同門檻，不必為了試一個參數就重跑推論
        result["height_ratio"] = float(box_height / height_reference)
        result["y2_ratio"] = float(y2 / image_height) if image_height else 0.0
        if (result["height_ratio"] < occluded_height_ratio
                and result["y2_ratio"] > OCCLUDED_Y2_RATIO):
            result["is_occluded"] = True

    return result


class FallAlarmGate:
    """告警的重複抑制：邊緣觸發，而不是永久閂鎖。

    ## 為什麼不能沿用原本的 vlm_triggered

    正式管線用一個 `vlm_triggered` 布林值：報過一次就永遠不再報。
    單人房間裡這是對的——同一個人跌倒不該把護理師的手機洗版。

    但公共區域不行：

        住民 A 跌倒 → 報警 → 旗標鎖上
        護理師處理完，三分鐘後住民 B 跌倒 → **不會報**

    ## 為什麼不做「每人一個閂鎖」

    那需要認得出誰是誰。追蹤 ID 會換——同一個人走出畫面再走回來就是新編號，
    於是同一次跌倒被重複報。要修得靠人臉／衣著比對，而本專案不做特徵辨識。

    ## 所以改成看「狀態」而不是看「人」

        待命 ──畫面上有人躺著──→ 已報警
        已報警 ──畫面上沒有人躺著了──→ 待命

    閘門完全不看 track_id，追蹤 ID 換人的問題就繞過去了。

    ⚠ **已知限制**：這套機制建立在「一次只會有一人跌倒」的前提上。
    A 躺在地上期間 B 也跌倒，B 不會被獨立發報（畫面上一直「有人躺著」，
    閘門沒有機會重新武裝）。這是不做身分辨識換來的簡化，取捨明確：
    公共區域同時兩人跌倒的機率遠低於「同一人被重複報」的困擾。
    需要涵蓋那種情境，就必須先做身分辨識。

    `clear_frames` 是重新武裝前要連續看到幾幀「地上沒人」。設 0 會讓
    偵測抖動（某一幀骨架沒抓到）就誤判為已淨空，接著重複發報。
    """

    def __init__(self, clear_frames=15):
        self.clear_frames = clear_frames
        self.armed = True
        self.clear_streak = 0

    def update(self, should_alert, anyone_down):
        """回傳這一幀要不要發報。**每個處理幀都必須呼叫一次**，否則重新武裝的
        連續計數會漏算，變成「地上還有人卻已重新武裝」。

        should_alert: 跌倒判斷是否成立（含音訊融合等其他來源）。
        anyone_down: 畫面上是否有任何人被幾何判定躺平/遮擋。

        兩個參數刻意分開：音訊融合可以在「畫面上沒人躺著」時單獨判定跌倒
        （modules/audio_fusion.py 聽到撞擊聲或呼救）。把重新武裝跟發報綁在
        同一個條件上，那種事件會被靜靜吃掉。
        """
        # 先更新武裝狀態，再決定要不要發報——順序反了會讓「剛淨空的那一幀」
        # 無法發報，而那正是音訊觸發最可能落在的位置
        if anyone_down:
            self.clear_streak = 0
        else:
            self.clear_streak += 1
            if self.clear_streak >= self.clear_frames:
                self.armed = True

        if should_alert and self.armed:
            self.armed = False
            return True
        return False

    def reset(self):
        """串流重連等情境：狀態全部歸零，重新武裝。"""
        self.armed = True
        self.clear_streak = 0

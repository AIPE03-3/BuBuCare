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
# 「躺平」的另一半：軀幹角量的是影像平面上肩→臀的方向，頭朝左躺是 ~0°、
# 頭朝右躺是 ~180°。現行規則只判 <40°，等於只抓到一半的躺姿。
LYING_ANGLE_DEG_UPPER = 140.0

# COCO 關鍵點索引
LEFT_SHOULDER, RIGHT_SHOULDER = 5, 6
LEFT_HIP, RIGHT_HIP = 11, 12
LEFT_KNEE, RIGHT_KNEE = 13, 14
LEFT_ANKLE, RIGHT_ANKLE = 15, 16


def body_is_cropped(keypoints):
    """下半身是不是不在框裡（膝與踝四點全數沒抓到）。

    ## 為什麼需要這個判斷

    `w/h > 1.25` 的前提是「框框住的是一整個人」。人走到畫面邊緣被切掉時，
    框只框到看得見的那一截——上半身的框天生就是寬扁形，`w/h` 直接爆掉。
    自錄 test6.mp4 的拍攝者站在右下角，腿被下緣切掉，`w/h` 1.25~1.52，
    軀幹角 99°~117°（明確站著），仍被判躺平，連報 13 幀。

    ## 為什麼用關鍵點而不是「框碰到畫面邊界」

    站在鏡頭前的人腳踝本來就在畫面下緣，框碰到邊界是常態，不代表被切掉。
    「膝踝四點全沒抓到」是下半身不在畫面裡的**直接證據**，不是位置的代理指標。

    ## ⚠ 這個判斷目前**沒有任何資料驗證過**，預設關閉

    寫它的動機是 test6.mp4 那 13 幀 `w/h` 誤報，當時判斷成「人走到畫面邊緣被
    切掉」。**後來查證發現那個判斷是錯的**：那個人的框完全在畫面內、四個下半身
    關鍵點也都抓到了。真正的成因是**高處鏡頭俯拍坐在桌前的人**——只有頭肩露在
    螢幕上方，投影出來就是寬扁形。跟裁切無關。

    量測結果：CAUCAFall test split 3062 幀有 0 幀觸發此判斷；test6 開關前後
    觸發幀數完全相同（15 → 15）。**所以它既不會讓結果變差，也還沒證明有用。**

    留著的理由：`features/*.npz` 已一併存下 `body_cropped`，等未來有真的含邊緣
    裁切的素材時可以直接離線量測，不必重跑 YOLO。要驗證它有效再考慮打開。
    """
    return all(keypoints[index][0] == 0 and keypoints[index][1] == 0
               for index in (LEFT_KNEE, RIGHT_KNEE, LEFT_ANKLE, RIGHT_ANKLE))

# ────────────────────────────────────────────────────────────────────────
# 躺平規則（防線 A）
#
# ⚠ 2026-07-30 實測發現現行規則的軀幹角那一條是**淨負面**的。
#   test split 30 支影片、逐幀比較（跌倒幀 181 / 正常影片幀 1583）：
#
#     規則                        跌倒幀命中   正常幀誤報
#     current  angle<40 or w/h     16.6%        5.9%
#     aspect   只有 w/h            14.9%        0.1%   ← 誤報少 59 倍
#     只有 angle<40                 3.3%        5.9%   ← 誤報全部來自這條
#     wide     angle<40|>140 or w/h 22.7%        8.0%
#
#   軀幹角在 2D 投影下分不出「躺著」和「彎腰撿東西」——兩者肩臀連線都接近水平。
#   加上 >140° 補回另一半躺姿確實提升召回，但同時把另一半彎腰也收進來，誤報更高。
#
#   高處/俯視鏡頭下更嚴重：躺在地上的人在影像上肩臀仍是上下分佈，角度接近 90°，
#   軀幹角完全沒有訊號（自錄 test6.mp8 實測，含真跌倒那一幀角度都在 99°~117°）。
# ────────────────────────────────────────────────────────────────────────
LYING_RULE_CURRENT = "current"    # 正式管線現況
LYING_RULE_ASPECT = "aspect"      # 只看寬高比
LYING_RULE_WIDE = "wide"          # 補上 >140° 的另一半躺姿
LYING_RULES = (LYING_RULE_CURRENT, LYING_RULE_ASPECT, LYING_RULE_WIDE)
DEFAULT_LYING_RULE = LYING_RULE_CURRENT


def check_lying_rule(name):
    """驗證規則名稱，回傳正規化字串。給 CLI 參數用。"""
    text = str(name).strip().lower()
    if text not in LYING_RULES:
        raise ValueError(f"未知的 lying_rule：{name!r}，可用：{LYING_RULES}")
    return text


def decide_lying(body_angle, aspect_ratio, lying_rule=DEFAULT_LYING_RULE,
                 body_cropped=False, crop_guard=False):
    """依規則判斷躺平。`body_angle` 為 None 代表肩或臀沒抓到，角度那一條直接跳過。

    刻意只吃純量（角度、寬高比、是否裁切），不吃關鍵點——這樣離線掃描可以直接
    拿 features/*.npz 裡存的原始數值重算，不必為了試一個規則就重跑一遍 YOLO。

    `crop_guard=True` 時，下半身不在框裡的人不採用 `w/h`（框不是完整人形，
    比例沒有意義），只留軀幹角那一條。
    """
    wide = aspect_ratio > LYING_ASPECT_RATIO
    if crop_guard and body_cropped:
        wide = False
    if lying_rule == LYING_RULE_ASPECT:
        return wide
    if body_angle is None:
        return wide
    if lying_rule == LYING_RULE_WIDE:
        return wide or body_angle < LYING_ANGLE_DEG or body_angle > LYING_ANGLE_DEG_UPPER
    return wide or body_angle < LYING_ANGLE_DEG


def person_geometry(keypoints, box_xywh, box_xyxy=None, image_height=0,
                    height_reference=None, occluded_height_ratio=0.0,
                    lying_rule=DEFAULT_LYING_RULE, crop_guard=False):
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
              "aspect_ratio": 0.0, "height_ratio": None, "y2_ratio": 0.0,
              "body_cropped": body_is_cropped(keypoints)}

    _, _, box_width, box_height = box_xywh
    aspect_ratio = float(box_width / box_height) if box_height else 0.0
    result["aspect_ratio"] = aspect_ratio

    # 防線 A：軀幹接近水平，或人框變成寬扁形
    shoulder_x = (keypoints[LEFT_SHOULDER][0] + keypoints[RIGHT_SHOULDER][0]) / 2.0
    shoulder_y = (keypoints[LEFT_SHOULDER][1] + keypoints[RIGHT_SHOULDER][1]) / 2.0
    hip_x = (keypoints[LEFT_HIP][0] + keypoints[RIGHT_HIP][0]) / 2.0
    hip_y = (keypoints[LEFT_HIP][1] + keypoints[RIGHT_HIP][1]) / 2.0
    if shoulder_x != 0 and hip_x != 0:  # xyn 為 0 代表該點沒抓到，不是「在畫面左上角」
        result["body_angle"] = float(np.abs(np.degrees(
            np.arctan2(hip_y - shoulder_y, hip_x - shoulder_x))))
    result["is_lying"] = decide_lying(result["body_angle"], aspect_ratio, lying_rule,
                                      result["body_cropped"], crop_guard)

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

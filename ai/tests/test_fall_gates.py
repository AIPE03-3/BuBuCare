# ai/tests/test_fall_gates.py
# 跌倒主迴圈兩個「閘門」的單元測試：
#   1. 無追蹤器那條退路的事件冷卻 / 重新武裝（docs/NEXT_STAGE.md 第 5 項）
#   2. 防線 B 參考身高的校正窗（docs/NEXT_STAGE.md 9-3）
#
# 這兩段原本是主迴圈裡的 inline 判斷，抽成純函式才驗得到 —— 整條 camera_worker 要
# Triton + 攝影機才跑得起來，端到端驗收另外做（見 PR 說明）。

import inference_test as it


# ── 1. 退路路徑的重新武裝 ────────────────────────────────────────────────────
# _fallback_rearm(armed, recovery_frames, falling, cooldown_until, now)
#   → (armed, recovery_frames)
# 規則：冷卻到期 **且** 畫面連續 _FALL_RECOVERY_FRAMES 個處理幀判非跌倒，才重新武裝。

RECOVERY = it._FALL_RECOVERY_FRAMES


def test_冷卻期內就算畫面早就回到正常也不重新武裝():
    armed, rec = it._fallback_rearm(
        armed=False, recovery_frames=RECOVERY * 10, falling=False,
        cooldown_until=1000.0, now=999.0,
    )
    assert armed is False


def test_冷卻到期但畫面仍判跌倒時不重新武裝且恢復計數歸零():
    armed, rec = it._fallback_rearm(
        armed=False, recovery_frames=RECOVERY, falling=True,
        cooldown_until=1000.0, now=2000.0,
    )
    assert armed is False
    assert rec == 0


def test_冷卻到期且恢復幀數足夠才重新武裝():
    armed, rec = it._fallback_rearm(
        armed=False, recovery_frames=RECOVERY - 1, falling=False,
        cooldown_until=1000.0, now=2000.0,
    )
    assert armed is True
    assert rec == 0


def test_恢復幀數還不夠時不重新武裝():
    armed, rec = it._fallback_rearm(
        armed=False, recovery_frames=0, falling=False,
        cooldown_until=0.0, now=2000.0,
    )
    assert armed is False
    assert rec == 1


def test_冷卻未到期時恢復計數持續累加不歸零():
    """冷卻一到期就要能立刻武裝，不該再從頭數 90 幀（兩個條件是並列，不是串接）。"""
    rec = 0
    armed = False
    for _ in range(RECOVERY * 2):
        armed, rec = it._fallback_rearm(
            armed=armed, recovery_frames=rec, falling=False,
            cooldown_until=1000.0, now=999.0,
        )
    assert armed is False
    assert rec >= RECOVERY          # 冷卻擋著，但恢復幀數已經數滿

    armed, rec = it._fallback_rearm(       # 冷卻一到期，下一幀就武裝
        armed=armed, recovery_frames=rec, falling=False,
        cooldown_until=1000.0, now=1000.0,
    )
    assert armed is True


def test_已武裝狀態不會被這個函式改掉():
    armed, rec = it._fallback_rearm(
        armed=True, recovery_frames=0, falling=True,
        cooldown_until=0.0, now=1.0,
    )
    assert armed is True


# ── 2. 防線 B 參考身高的校正窗 ───────────────────────────────────────────────

def test_開機後落在校正窗內():
    assert it._in_calibration_window(frame_count=20, calib_frame0=0) is True


def test_過了校正窗就不再取樣():
    assert it._in_calibration_window(frame_count=50, calib_frame0=0) is False


def test_換來源重設後仍然進得了校正窗():
    """缺陷三的回歸測試。

    校正窗原本寫死絕對的 frame_count（10~40），而 frame_count 只進不出 ——
    那時候換攝影機／改構圖只把 normal_h_reference 設回 None **是無效的**：
    跑到第 1000 幀時永遠進不了 10~40，參考值會卡在 None、防線 B 整條失效。
    """
    assert it._in_calibration_window(frame_count=1020, calib_frame0=1000) is True
    assert it._in_calibration_window(frame_count=1005, calib_frame0=1000) is False
    assert it._in_calibration_window(frame_count=1050, calib_frame0=1000) is False


def test_校正窗的邊界是開區間():
    assert it._in_calibration_window(it._HREF_CALIB_FROM, 0) is False
    assert it._in_calibration_window(it._HREF_CALIB_FROM + 1, 0) is True
    assert it._in_calibration_window(it._HREF_CALIB_TO - 1, 0) is True
    assert it._in_calibration_window(it._HREF_CALIB_TO, 0) is False

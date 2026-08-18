# 測 GET /health 與 GET /metrics（observability/router.py）
# 以及「人工判定會讓 Prometheus 指標 +1」這條鏈路
from prometheus_client import REGISTRY


def 讀指標(verdict: str) -> float:
    # REGISTRY.get_sample_value 是 prometheus_client 官方提供給測試用的讀值方式，
    # 不去戳 Counter 的私有變數。查不到會回 None——帶標籤的指標「第一次用到才誕生」，
    # 所以在還沒有人判定過的時候那一格是不存在的（不是 0），故用 or 0.0 補成 0。
    return REGISTRY.get_sample_value("event_verdict_total", {"verdict": verdict}) or 0.0


def test_health_回ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_health_不需登入(client):
    # 部署腳本 gcp_vm_environment/deploy_dev.sh 用這條當探針，不帶任何 token
    res = client.get("/health")
    assert res.status_code == 200


def test_metrics_回純文字不是json(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    # Prometheus 只吃純文字格式。若哪天有人把 Response(...) 拿掉直接 return，
    # 這裡會變成 application/json，功能測試不會紅但 Prometheus 抓不到，故守在這裡
    assert res.headers["content-type"].startswith("text/plain")


def test_metrics_含自訂指標的名稱與說明(client):
    res = client.get("/metrics")
    # 指標定義在 events/router.py，這裡抓得到＝prometheus_client 的全域登記簿正常運作
    # （兩個檔案之間沒有 import 關係，靠登記簿串起來）
    assert "event_verdict_total" in res.text
    assert "人工判定次數" in res.text


def test_判誤報_指標的false_alarm加一(client, auth_headers, make_event):
    # Counter 是行程層級的全域狀態，不會隨測試結束歸零（前面的測試判定過就已經有數字），
    # 所以不能斷言「等於 1」，要比動作前後的差值
    before = 讀指標("false_alarm")
    event = make_event()

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert 讀指標("false_alarm") == before + 1


def test_判真跌倒_指標的true_alarm加一(client, auth_headers, make_event):
    # 跟上一支幾乎一樣但不可省：這支才擋得住「標籤值被寫死成 false_alarm」
    # ——那種寫法上一支測試照樣會過，但真跌倒會被算成誤報，誤報率永遠 100%
    before_true = 讀指標("true_alarm")
    before_false = 讀指標("false_alarm")
    event = make_event()

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "true_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert 讀指標("true_alarm") == before_true + 1
    assert 讀指標("false_alarm") == before_false  # 沒有記錯格


def test_被擋掉的判定不計數(client, auth_headers, make_event):
    # 請求被守門擋掉（409）時指標不該動。
    # 注意這支的守備範圍：它擋得住「.inc() 被搬到 409 守門之前」，但擋不住
    # 「.inc() 被搬到 db.commit() 前一行」——因為 409 在那之前就 raise 了。
    # 要測「commit 失敗時不計數」得去 mock db.commit 拋錯，成本較高，目前沒做。
    before = 讀指標("false_alarm")
    event = make_event(status="in_progress", verdict="true_alarm", verdict_by="boss")

    res = client.patch(
        f"/events/{event.event_id}/verdict",
        json={"verdict": "false_alarm"},
        headers=auth_headers,
    )
    assert res.status_code == 409
    assert 讀指標("false_alarm") == before

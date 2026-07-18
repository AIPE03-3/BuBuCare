# test_register.py
# 過渡版：欄位改名後的最小驗證。Task 2 改 admin-only 時整檔重寫。


def test_register_new_user_returns_success_message(client):
    # 用全新員編註冊 → 成功，訊息包含員編
    response = client.post("/register", json={
        "employee_id": "E100", "full_name": "新同事", "password": "pass123"})
    assert response.status_code == 200
    assert "E100" in response.json()["message"]


def test_register_duplicate_employee_id_returns_400(client):
    # alice 已在 conftest 建好，再用同員編註冊 → 400
    response = client.post("/register", json={
        "employee_id": "alice", "full_name": "冒牌貨", "password": "anything"})
    assert response.status_code == 400


def test_register_without_email_succeeds(client):
    # email 改成選填，不給也能註冊成功
    response = client.post("/register", json={
        "employee_id": "E101", "full_name": "沒信箱", "password": "pass123"})
    assert response.status_code == 200

# 測 GET /staff：前端「指派照護員」下拉選單的資料來源


def test_未登入_401(client):
    res = client.get("/staff")
    assert res.status_code == 401


def test_回傳照護員名單(client, auth_headers):
    res = client.get("/staff", headers=auth_headers)
    assert res.status_code == 200
    names = [s["staff_name"] for s in res.json()]
    assert names == ["小美", "阿強"]  # conftest 種子資料

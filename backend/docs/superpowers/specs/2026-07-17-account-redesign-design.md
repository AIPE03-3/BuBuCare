# 帳號系統改版設計（員編登入 + admin 開帳號 / 重設密碼）

## 目標

把「使用者自取帳號、公開註冊」改成「員編登入、admin 開帳號」：

- `user_account.name` 拆成 `employee_id`（登入用員編）+ `full_name`（真實姓名）
- `POST /register` 從公開改 admin-only；忘記密碼不再靠 email，改由 admin 重設
- 新增「首次登入強制改密碼」與「軟刪除（停用）」機制

## 為什麼

員編是機構既有人資編號，不該讓任何人自稱一組員編就能公開註冊佔走；
安養院員工帳號的生命週期（到職開帳號、忘記密碼、離職停用）都該由 admin 管理。

## Schema 改動（`user_account` 表）

| 欄位                     | 型別                     | Nullable         | 說明                                                                                            |
| ------------------------ | ------------------------ | ---------------- | ----------------------------------------------------------------------------------------------- |
| `id`                   | Integer（PK）            | 否               | 不變                                                                                            |
| ~~`name`~~            | -                        | -                | 移除，拆成`employee_id` + `full_name`                                                       |
| `employee_id`          | String, unique           | 否               | 登入用的員工編號（與前端確認過命名，前端`AuthSession` 預留的 `employee_code` 改叫這個名字） |
| `full_name`            | String                   | 否               | 真實姓名                                                                                        |
| `password`             | String                   | 否               | 雜湊值，不變                                                                                    |
| `email`                | String, unique           | 是（原本否）     | 不再是找回密碼的管道，改選填                                                                    |
| `role`                 | Enum（staff／admin）     | 否               | 從 String 改原生 Enum，做法比照 status／verdict／severity                                       |
| `must_change_password` | Boolean                  | 否，預設`True` | admin 開的新帳號要求首次登入改密碼；種子帳號（admin/staff01）由種子腳本手動設`False`          |
| `is_active`            | Boolean                  | 否，預設`True` | 軟刪除用，取代硬刪除                                                                            |
| `last_login_time`      | DateTime                 | 是               | 不變                                                                                            |
| `company_id`           | Integer（FK→companies） | 否               | 不變                                                                                            |

### 既有資料的遷移方式

開發階段直接清掉 `user_account` 既有資料、砍表重建：重跑 `python -m backend.init_db`
依新 models.py 建表＋重種帳號，不逐條手寫 ALTER。
已確認沒有其他表的外鍵指向 `user_account`，砍表不牽連別的表。

## API 規格

### `POST /register`（改 admin-only）

- 權限：需 admin（`require_admin`）
- Request：`employee_id`／`full_name`／`role`（staff|admin）／`password`（admin 手動輸入的臨時密碼）／`email`（選填）
- 員編重複回 400；email 有填且重複回 400（不能放給 unique 約束炸 500）
- 成功回 **201**：

```json
{ "id": 7, "employee_id": "E003", "full_name": "陳小華", "role": "staff" }
```

### `POST /login`

- 查帳號依據從 `User.name` 改成 `User.employee_id`
- `is_active=False` 回 401，訊息與帳密錯誤相同（不透露帳號被停用）
- 成功回應多帶 `must_change_password`：

```json
{ "access_token": "eyJ...", "token_type": "bearer", "must_change_password": true }
```

### `GET /me`

- 全部從 JWT payload 拿、不查資料庫，回：

```json
{ "employee_id": "E001", "full_name": "王小明", "role": "staff" }
```

### `PATCH /me/password`（新增）

- 權限：需登入
- Request：`old_password` + `new_password`
- 舊密碼錯誤回 **400**（不用 401——前端慣例把 401 當 token 失效、會把人踢回登入頁）
- 成功後把 `must_change_password` 設回 `False`

### `PATCH /users/{id}/password`（新增）

- 權限：admin-only
- Request：`new_password`（admin 給的新臨時密碼）
- 成功後把 `must_change_password` 設為 `True`
- 不特別擋已停用帳號（登入時 `is_active` 會擋）

### `DELETE /users/{id}`

- 從硬刪除改成把 `is_active` 設為 `False`（軟刪除）
- admin 不能停用自己（防止最後一個 admin 把自己鎖死），違反回 400

### 密碼規則（三處共用）

register 的臨時密碼、兩個改密碼端點的 `new_password`，統一用 Pydantic `min_length=6`。
種子帳號密碼 `123456` 剛好 6 碼，不受影響。

## JWT 改動

`create_access_token` 的 `sub` 改放 `employee_id`，`full_name` 一併塞進 payload，
讓 `/me` 不用查資料庫。姓名異動的顯示延遲，最長不超過 token 有效期（1 天）。

`must_change_password` **不放進 JWT**，只放在 `/login` 回應的普通欄位。搭配新端點的完整流程：

1. admin 開帳號給新員工，給臨時密碼，DB 的 `must_change_password = True`
2. 員工登入，`/login` 回應帶 `"must_change_password": true`
   → 前端看到 true，把人導去「設定新密碼」頁，不放行進系統
3. 員工填舊密碼＋新密碼，前端打 `PATCH /me/password`
   → 後端驗舊密碼、存新密碼、把 DB 的 `must_change_password` 改回 `False`，回 200
4. 前端收到 200，關掉本地的「要改密碼」狀態，放行

不放進 JWT 的原因：token 產生後內容不可變。若把 `must_change_password` 印進 token，
步驟 3 改完密碼後，員工手上的 token 裡仍是 `true`，前端會一直把人踢回改密碼頁，
直到 token 過期（最長 1 天）。

## 已知限制（刻意接受，不在本輪處理）

- **停用帳號的舊 token 殘留**：`get_current_user` 只解 token 不查資料庫，
  `is_active=False` 後既有 token 到過期前（最長 1 天）仍可用所有需登入的端點。
  未來靠 future-work 第 1 項（短效 access token）縮小窗口，不在 `get_current_user` 加每請求查庫。
- **改密碼前不擋其他 API**：`must_change_password=True` 期間後端不阻擋其他端點，靠前端引導。

## 測試策略

TDD。受影響與新增的測試：

- `conftest.py`：種子帳號 alice / boss 換新欄位
- `test_register.py`：整組重寫成 admin-only 情境（無 token 401／staff 403／admin 成功 201／重複員編 400／重複 email 400／密碼過短 422）
- `test_login.py`：改用 employee_id 登入；停用帳號 401；回應含 `must_change_password`
- `test_me.py`：新回傳格式三欄位
- `test_admin.py`：DELETE 改驗軟刪除；不能停用自己
- `test_sse.py`：`sub` 斷言改 employee_id
- 新增：`PATCH /me/password`（成功／舊密碼錯 400／改完 flag 歸 False）、
  `PATCH /users/{id}/password`（admin 成功／非 admin 403／改完 flag 設 True）

## 連鎖改動檔案清單

| 檔案                                              | 要動什麼                                                                                                                                                              |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/core/models.py`                        | `User` 欄位改動本體                                                                                                                                                 |
| `backend/users/router.py`                       | 既有 4 個端點改寫 + 2 個新端點                                                                                                                                        |
| `backend/init_db.py`                            | `seed_accounts` 改用 `employee_id` + `full_name`，種子帳號手動設 `must_change_password=False`                                                                 |
| `backend/tests/`                                | 見上方測試策略                                                                                                                                                        |
| `CLAUDE.md`                                     | API 路由表、資料庫欄位段落同步                                                                                                                                        |
| 前端`frontend/src/api/auth/employeePassword.ts` | `display_name` 目前拿 `sub`，改版後會顯示員編；`JwtPayload` 要加 `full_name`；`AuthSession` 預留的 `employee_code` 統一叫 `employee_id`——通知前端組員 |

## 已記入 `backend/docs/future-work.md`，本輪不處理

- 事件判定／結案要記錄操作者（稽核追蹤）
- `user_account` 與 `staff` 是否該建立關聯
- 初始 admin 密碼改用環境變數指定
- 多租戶「選機構登入」
- 軟刪除的復職端點（把 `is_active` 改回 `True`）

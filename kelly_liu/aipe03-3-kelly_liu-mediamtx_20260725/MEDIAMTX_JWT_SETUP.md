# MediaMTX + JWT 即時監控設定

本版本不修改原專案；它是獨立副本。登入 JWT 只送後端，前端先用它向
`POST /streams/{camera_path}/token` 換取 60 秒串流 JWT，再以
`Authorization: Bearer <stream-token>` 呼叫 MediaMTX WHEP。

## 本機啟動重點

1. 由 `.env.example` 建立 `.env`，設定既有 `SECRET_KEY`、攝影機帳密。
2. 由 `mediamtx/mediamtx-local.yml.example` 建立不進 git 的 `mediamtx-local.yml`。
3. 由 `frontend/.env.example` 建立 `frontend/.env`。
4. 啟動 FastAPI、MediaMTX、前端；登入後開啟「即時監控」，點選線上攝影機。

若 FastAPI 不在 Docker 內，將 `authHTTPAddress` 的 `host.docker.internal`
改成 MediaMTX 可連到的實際後端位址。正式網站為 HTTPS 時，MediaMTX WHEP
也必須使用 HTTPS，否則瀏覽器會因 mixed content 阻擋。

## 安全界線

- `/streams/{camera_path}/token` 由既有 `get_current_user` 保護。
- `/streams/auth` 的觀看請求僅接受 `action=read`、`protocol=webrtc`，並比對
  JWT 的 `scope=stream` 與 `path`；publish 則使用環境變數中的獨立推流帳密。
- 串流斷線時會重新換票；不循環續票、不重用舊票。
- MediaMTX 不會誤用觀眾串流 JWT 放行 publish。

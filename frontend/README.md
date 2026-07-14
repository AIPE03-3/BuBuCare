# Fulilian 中控台前端

長照機構跌倒偵測中控台（React SPA）。使用者為護理站值班人員與系統管理者。

## 四條鐵律（違反即重做）

1. 元件內**禁止直接 fetch／axios**，資料一律經 `src/api/` 取得。
2. **禁止寫死色碼**（hex、rgb、Tailwind 色名如 red-500 皆禁止），顏色一律引用 tokens 變數。
3. 事件狀態顯示文字一律走 `STATUS_LABEL` 對照表，禁止散落硬編碼。
4. 登入相關元件**禁止 import 具體 auth provider**，只能經 `src/api/auth/index.ts`。

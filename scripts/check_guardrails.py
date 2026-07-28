#!/usr/bin/env python3
"""專案護欄檢查：擋住「跨機器會炸」與「不該進 repo」的東西。

為什麼需要這支：本專案同時在兩台機器上開發（Linux + RTX 5060 Ti、macOS），
兩邊踩過的雷都是同一批——寫死家目錄絕對路徑、把 GB 級模型/影片 commit 進來、
明文密碼進版控、動到後端的 Kafka payload 契約。這些靠 code review 抓很累，
交給機器一次講清楚。

用法：
    python3 scripts/check_guardrails.py            # 檢查所有 git 追蹤的檔案（CI 用）
    python3 scripts/check_guardrails.py a.py b.sh  # 只檢查指定檔案（pre-commit hook 用）

只用標準函式庫，macOS / Linux 都能跑，不需要裝任何東西。
退出碼 0＝過，1＝有問題（訊息會直接寫出「怎麼修」）。

要放行個別特例，在該行尾端加註解： # guardrail: allow
"""
import ast
import os
import re
import subprocess
import sys

# ── 規則參數 ────────────────────────────────────────────────────────────────
MAX_FILE_MB = 10  # 單檔大小上限；GitHub 硬上限是 100MB，這裡抓更緊留餘裕

ALLOW_MARK = "guardrail: allow"  # 行尾加這個註解＝本行豁免

# 家目錄絕對路徑：macOS 是 /Users/<人名>/，Linux 是 /home/<人名>/。
# 只抓「後面還接了人名」的形式，避免誤殺 /home 或 /usr 這種系統路徑。
ABS_PATH_RE = re.compile(r"['\"](/home/[a-zA-Z0-9_.-]+/|/Users/[a-zA-Z0-9_.-]+/)")

# 明文密碼/金鑰：抓「賦值成字面字串」的形式；讀環境變數的寫法不算。
SECRET_RE = re.compile(
    r"""(?ix)
    (password|passwd|secret|api[_-]?key|access[_-]?key|token)
    \s* [:=] \s*
    ['"](?P<val>[^'"\s$]{6,})['"]   # 至少 6 字元、不含 $（排除 "${VAR}" 這種展開）
    """
)
AKIA_RE = re.compile(r"AKIA[0-9A-Z]{16}")  # AWS access key id 固定格式

# 明顯是假資料/佔位符的值 → 不算洩密（測試 fixture、範例檔常見，硬報會變狼來了）
PLACEHOLDER_RE = re.compile(
    r"(?i)^(x{3,}|\.{3,}|-+)"                       # 開頭就是 XXXX / .... / ----
    r"|(?:dummy|example|placeholder|changeme|sample" # 或值裡含這些字眼
    r"|fake|test|bad-|invalid|your[_-]|\.\.\.)"
)

# 掃原始碼的副檔名（二進位/資料檔不掃內容，只檢查大小）
TEXT_EXTS = {".py", ".sh", ".yml", ".yaml", ".conf", ".toml", ".env", ".json"}

# ⚠️ 後端契約：inference_test.route_by_confidence() 送出的 payload 欄位。
# 這組是 AI 端每則事件都必須送齊的欄位。後端 EventCreateRequest（backend/events/router.py）
# 認得其中 7 欄：device_id/event_type/clip_path/detected_at 必填（少送才會 422），
# snapshot_path/yolo_score/vlm_summary 選填；image_filename 後端忽略，但 AI 端自己要用。
# 注意後端沒設 model_config，Pydantic 預設 extra="ignore" → 多送不會 422，只會被靜默丟掉。
# 所以這裡擋的是「少送」，不是「多送」。動這組＝動契約，必須先跟後端組講好。
CONTRACT_KEYS = {
    "device_id", "event_type", "clip_path", "detected_at", "snapshot_path",
    "image_filename", "yolo_score", "vlm_summary",
}
# 只在 AI 內部流通、刻意不外發後端的欄位，允許在 payload 裡額外出現。
# yolo_threshold 只出現在慢速道（nursing-home-alerts → vlm_worker / agent）：agent 的
# judge prompt 要拿它跟 yolo_score 比大小（見 agent/prompts.py 的 describe_score_vs_threshold，
# 那是防地端小模型自己比錯大小的防呆）。二審端重組外發 payload 時不會把它帶去後端。
INTERNAL_ONLY_KEYS = {"yolo_threshold"}
CONTRACT_FILE = "ai/inference_test.py"
CONTRACT_FUNC = "route_by_confidence"

# ⚠️ ai/modules/ 白名單：只准存在、也只准 import 這兩個檔（理由見根目錄 CLAUDE.md）。
# 2026-07-27 刪掉 bed_exit / wandering / micro_motion / audio_fusion / chair_slip 五個模組：
# 前三個繞過 route_by_confidence() 自組 payload 直送 Kafka，欄位對不上契約、每則都被後端
# 422 退件（用 test4.mp4 實測確認）；audio_fusion 是每 22 秒隨機丟假撞擊聲的展示用產生器，
# 是誤報來源不是偵測能力。跌倒主邏輯本來就在 inference_test.py 主迴圈，不在 modules/ 底下。
# 為什麼要機器擋：這種「模組自己送 Kafka」的破口靠 code review 抓不到——它跑得動、
# 不噴錯，只是訊息在後端被靜默丟掉，要跑夠長的影片才會曝露。
MODULES_DIR = "ai/modules"
MODULES_ALLOW = {"__init__.py", "sanity_check.py"}
# import 形式：`from modules.X import ...` / `import modules.X` / `from ai.modules.X import ...`
MODULES_PREFIXES = ("modules.", "ai.modules.")


# 既有豁免清單：專案早於本護欄就存在的違規，一次性放行（護欄要擋的是「新」的違規，
# 不是把陳年舊帳翻出來擋住所有人 commit）。格式見該檔說明。
ALLOWLIST_FILE = "scripts/guardrails_allow.txt"


def _load_allowlist(root: str) -> set[str]:
    p = os.path.join(root, ALLOWLIST_FILE)
    if not os.path.isfile(p):
        return set()
    out = set()
    for line in open(p, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            out.add(line)
    return out


def _repo_root() -> str:
    return subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _tracked_files(root: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True, cwd=root
    ).stdout.split("\n")
    return [f for f in out if f]


def check_big_files(root: str, files: list[str], problems: list[str], allow: set[str]) -> None:
    limit = MAX_FILE_MB * 1024 * 1024
    for f in files:
        if f"size:{f}" in allow:
            continue
        p = os.path.join(root, f)
        if not os.path.isfile(p):
            continue
        size = os.path.getsize(p)
        if size > limit:
            problems.append(
                f"❌ 大檔：{f}（{size / 1024 / 1024:.0f}MB > {MAX_FILE_MB}MB）\n"
                f"   → 模型權重、影片、資料集不進 repo。加進 .gitignore，\n"
                f"     模型用 `python ai/export_models.py` 在各自機器上重建。"
            )


def check_text(root: str, files: list[str], problems: list[str], allow: set[str]) -> None:
    for f in files:
        if os.path.splitext(f)[1] not in TEXT_EXTS:
            continue
        p = os.path.join(root, f)
        if not os.path.isfile(p):
            continue
        try:
            lines = open(p, encoding="utf-8").read().split("\n")
        except (UnicodeDecodeError, OSError):
            continue
        skip_abs = f"abspath:{f}" in allow
        skip_secret = f"secret:{f}" in allow
        for i, line in enumerate(lines, 1):
            if ALLOW_MARK in line:
                continue
            if ABS_PATH_RE.search(line) and not skip_abs:
                problems.append(
                    f"❌ 寫死家目錄絕對路徑：{f}:{i}\n"
                    f"   {line.strip()[:100]}\n"
                    f"   → 換一台機器就失效（Linux /home/ vs macOS /Users/）。\n"
                    f"     改成以 __file__ 為基準，照 ai/inference_test.py 的做法：\n"
                    f"       _AI_DIR = os.path.dirname(os.path.abspath(__file__))\n"
                    f"       path = os.path.join(_AI_DIR, 'test_demo', 'test1.mp4')\n"
                    f"     或改讀環境變數（給預設值）：os.environ.get('X', '<預設>')"
                )
            m = SECRET_RE.search(line)
            is_placeholder = bool(m and PLACEHOLDER_RE.search(m.group("val")))
            if (m and not is_placeholder or AKIA_RE.search(line)) and not skip_secret:
                problems.append(
                    f"❌ 疑似明文密碼/金鑰：{f}:{i}\n"
                    f"   {line.strip()[:100]}\n"
                    f"   → 改讀環境變數或 .env（.env 已在 .gitignore）：\n"
                    f"       os.environ['XXX']  /  os.environ.get('XXX', '')\n"
                    f"     真的是假資料（測試用）就在行尾加註解： # {ALLOW_MARK}"
                )


def check_contract(root: str, files: list[str], problems: list[str]) -> None:
    """比對 route_by_confidence() 送出的 payload 欄位有沒有被動到。

    用 ast 靜態解析，不 import（import 會去連 Kafka/Triton）。
    """
    if CONTRACT_FILE not in files:
        return
    p = os.path.join(root, CONTRACT_FILE)
    if not os.path.isfile(p):
        return
    try:
        tree = ast.parse(open(p, encoding="utf-8").read())
    except SyntaxError as e:
        problems.append(f"❌ {CONTRACT_FILE} 語法錯誤：{e}")
        return

    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == CONTRACT_FUNC):
            continue
        for sub in ast.walk(node):
            # 只看指派給 payload 的 dict 字面值
            if not (isinstance(sub, ast.Assign) and isinstance(sub.value, ast.Dict)):
                continue
            if not any(getattr(t, "id", None) == "payload" for t in sub.targets):
                continue
            keys = {k.value for k in sub.value.keys if isinstance(k, ast.Constant)}
            missing = CONTRACT_KEYS - keys
            extra = keys - CONTRACT_KEYS - INTERNAL_ONLY_KEYS
            if missing or extra:
                problems.append(
                    f"❌ 動到後端契約：{CONTRACT_FILE} 的 {CONTRACT_FUNC}() payload 欄位變了\n"
                    + (f"   少了：{sorted(missing)}\n" if missing else "")
                    + (f"   多了：{sorted(extra)}\n" if extra else "")
                    + "   → 少了：這組是 AI 端每則事件都要送齊的欄位，其中 device_id/event_type/\n"
                      "     clip_path/detected_at 是後端必填，少送會被 422 退件。\n"
                      "   → 多了：後端 Pydantic 預設 extra=\"ignore\"，多送不會 422，但會被靜默丟掉，\n"
                      "     等於白送。純 AI 內部用的欄位請加進 INTERNAL_ONLY_KEYS 並註明用途。\n"
                      "     要改必須先跟後端組談好、兩邊同時改。改了跑得動 ≠ 沒破壞契約。\n"
                      "     若確定後端已同步更新，改 scripts/check_guardrails.py 的 CONTRACT_KEYS。"
                )
    return


def _module_name(dotted: str) -> str | None:
    """從 `modules.chair_slip` / `ai.modules.chair_slip` 抽出模組名，非本目錄回 None。"""
    for prefix in MODULES_PREFIXES:
        if dotted == prefix.rstrip(".") or dotted.startswith(prefix):
            rest = dotted[len(prefix):] if dotted.startswith(prefix) else ""
            return rest.split(".")[0] if rest else ""
    return None


def check_module_whitelist(root: str, files: list[str], problems: list[str]) -> None:
    """擋兩件事：在 ai/modules/ 新增非白名單檔案、以及 import 非白名單模組。

    用 ast 靜態解析，不 import（import 會去連 Kafka/Triton）。只掃 .py，
    所以文件裡提到模組名不會被誤擋。
    """
    allowed_stems = {os.path.splitext(f)[0] for f in MODULES_ALLOW}
    hint = (
        f"   → {MODULES_DIR}/ 只准存在、也只准 import：{', '.join(sorted(MODULES_ALLOW))}\n"
        "     其餘五個模組已於 2026-07-27 刪除（自組 payload 繞過契約被後端 422、\n"
        "     audio_fusion 是隨機假資料產生器），功能與邏輯一律不再套用。\n"
        "     跌倒主邏輯在 ai/inference_test.py 主迴圈，不在 modules/ 底下。\n"
        "     理由與「真的要復活」的完整流程見根目錄 CLAUDE.md。"
    )

    for f in files:
        # 規則 1：不准在 ai/modules/ 新增非白名單檔案
        norm = f.replace(os.sep, "/")
        if norm.startswith(MODULES_DIR + "/"):
            rel = norm[len(MODULES_DIR) + 1:]
            if "/" in rel or rel not in MODULES_ALLOW:
                problems.append(f"❌ {MODULES_DIR} 白名單：不該有這個檔案 {f}\n" + hint)

        # 規則 2：不准 import 非白名單模組
        if os.path.splitext(f)[1] != ".py":
            continue
        p = os.path.join(root, f)
        if not os.path.isfile(p):
            continue
        try:
            src = open(p, encoding="utf-8").read()
            tree = ast.parse(src)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue  # 語法錯誤由 check_contract 對契約檔負責回報，這裡不重複噴
        lines = src.split("\n")
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                targets = [node.module]
            for dotted in targets:
                name = _module_name(dotted)
                if name is None or name == "" or name in allowed_stems:
                    continue
                line_no = getattr(node, "lineno", 0)
                if 0 < line_no <= len(lines) and ALLOW_MARK in lines[line_no - 1]:
                    continue
                problems.append(
                    f"❌ {MODULES_DIR} 白名單：{f}:{line_no} import 了已封印的模組 `{name}`\n"
                    f"   {lines[line_no - 1].strip()[:100] if 0 < line_no <= len(lines) else ''}\n"
                    + hint
                )


def main() -> int:
    root = _repo_root()
    files = sys.argv[1:] or _tracked_files(root)
    allow = _load_allowlist(root)
    problems: list[str] = []

    check_big_files(root, files, problems, allow)
    check_text(root, files, problems, allow)
    check_contract(root, files, problems)
    check_module_whitelist(root, files, problems)

    if problems:
        print("\n" + "=" * 70)
        print(f"護欄檢查沒過（{len(problems)} 項）")
        print("=" * 70)
        for p in problems:
            print("\n" + p)
        print("\n" + "=" * 70)
        print("這些規則是兩台機器（Linux/macOS）協作踩過的雷，不是形式主義。")
        print("每則訊息都附了怎麼修。真有正當理由要放行，在該行尾加： # " + ALLOW_MARK)
        print("=" * 70)
        return 1

    print(f"✅ 護欄檢查通過（掃了 {len(files)} 個檔案）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

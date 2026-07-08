#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PreToolUse hook：偵測 git commit 指令，強制跳出確認框
#
# Claude Code 在每次要跑 Bash/PowerShell 前，會把指令內容用 JSON 從 stdin 餵進來。
# 這支腳本檢查裡面有沒有 "git commit"：
#   有  → 回傳 permissionDecision=ask，讓 Claude Code 一定跳出確認框問你
#   沒有 → 不輸出任何東西（exit 0），照原本流程走
import json
import re
import sys

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)  # 讀不到就放行，hook 絕不擋住正常流程

command = (data.get("tool_input") or {}).get("command", "")

# 抓「git ... commit」：git 後面 40 字元內出現 commit 子指令就算數
# （涵蓋 git commit -m、git -C path commit 等寫法）
if re.search(r"\bgit\b.{0,40}\bcommit\b", command):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "依專案合作規則：git commit 前請先向使用者確認再執行。",
        }
    }))

sys.exit(0)

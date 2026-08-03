# ai/tests/conftest.py
# AI 端單元測試的共用設定。
#
# 為什麼需要這支：ai/ 底下的模組彼此是「同層 import」（inference_test.py 裡寫的是
# `from triton_pose_client import ...`、`from modules.sanity_check import ...`），
# 那是為了讓 `cd ai && python inference_test.py` 直接跑得起來。從 repo 根目錄跑 pytest 時
# ai/ 不在 sys.path 上，所以在這裡補進去。
#
# ⚠️ `import inference_test` 有 import 期副作用：會建一個 KafkaProducer（有 try/except，
# 沒 Kafka 也只是印一行警告）並載入 torch / ultralytics，約 3 秒。這是既有結構，
# 不在本批的修改範圍；測試本身不碰任何外部服務。

import sys
from pathlib import Path

AI_DIR = Path(__file__).resolve().parents[1]
if str(AI_DIR) not in sys.path:
    sys.path.insert(0, str(AI_DIR))

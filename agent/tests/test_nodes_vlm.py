# agent/tests/test_nodes_vlm.py
# 驗收重點（WBS P1.2）：mock ollama 下重試/逾時路徑皆有測試。

import pytest

from agent.nodes.vlm import OllamaVlmClient, VlmError, analyze_with_retry, make_vlm_node
from agent.schemas import AlertMessage

ALERT = AlertMessage(event_type="Fall_Detected", camera_id="101", yolo_score=0.72)


class FakeVlmClient:
    """照腳本回應的假 VLM：字串就回傳，Exception 就丟出來。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def analyze(self, image_path, prompt):
        self.calls.append({"image_path": image_path, "prompt": prompt})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ── 重試政策 ────────────────────────────────────────────
def test_第一次就成功不重試():
    client = FakeVlmClient(["報告內容"])

    report, error = analyze_with_retry(client, "/img.jpg", "prompt", max_retries=2)

    assert (report, error) == ("報告內容", None)
    assert len(client.calls) == 1


def test_失敗後重試並成功():
    client = FakeVlmClient([VlmError("逾時"), "第二次成功"])

    report, error = analyze_with_retry(client, "/img.jpg", "prompt", max_retries=2)

    assert report == "第二次成功"
    assert len(client.calls) == 2


def test_重試上限是首次加重試次數():
    # max_retries=2 → 首次 + 重試 2 次 = 共 3 次呼叫
    client = FakeVlmClient([VlmError("x")] * 3)

    report, error = analyze_with_retry(client, "/img.jpg", "prompt", max_retries=2)

    assert report is None
    assert "x" in error
    assert len(client.calls) == 3


def test_不重試的設定只呼叫一次():
    client = FakeVlmClient([VlmError("x")])

    analyze_with_retry(client, "/img.jpg", "prompt", max_retries=0)

    assert len(client.calls) == 1


# ── 節點行為 ────────────────────────────────────────────
def test_節點成功時把報告放進_state():
    node = make_vlm_node(FakeVlmClient(["【安養中心緊急通報】…"]), max_retries=2)

    result = node({"alert": ALERT, "image_path": "/img.jpg"})

    assert result["vlm_report"].startswith("【安養中心緊急通報】")


def test_節點重試耗盡時不丟例外():
    # 這是關鍵：VLM 掛掉不能讓 consumer 停擺，交給 judge 降級成「交回人工」
    node = make_vlm_node(FakeVlmClient([VlmError("連不上")] * 3), max_retries=2)

    result = node({"alert": ALERT, "image_path": "/img.jpg"})

    assert result["vlm_report"] is None


def test_節點會帶入追問內容():
    client = FakeVlmClient(["補充後的報告"])
    node = make_vlm_node(client, max_retries=2)

    node({"alert": ALERT, "image_path": "/img.jpg", "followup": "【補充追問】請描述姿態"})

    assert "【補充追問】請描述姿態" in client.calls[0]["prompt"]


def test_首次判讀不帶追問內容():
    client = FakeVlmClient(["報告"])
    node = make_vlm_node(client, max_retries=2)

    node({"alert": ALERT, "image_path": "/img.jpg"})

    assert "【補充追問】" not in client.calls[0]["prompt"]


def test_prompt_不得洩漏誘導資訊():
    """二審的意義是獨立查證，不是幫邊緣端背書。

    舊 prompt（沿用 vlm_worker）先說「偵測到 Fall_Detected、置信度 72%」再要模型
    填【緊急通報】表格，實測讓它把站立行走的人描述成「可能有跌倒風險、風險評級：高」。
    這條測試釘住：不准把事件類型與邊緣端分數餵給 VLM。
    """
    client = FakeVlmClient(["報告"])
    make_vlm_node(client, max_retries=2)({"alert": ALERT, "image_path": "/img.jpg"})

    prompt = client.calls[0]["prompt"]
    assert "Fall_Detected" not in prompt
    assert "72" not in prompt          # yolo_score 0.72 不得以任何形式出現
    assert "緊急通報" not in prompt     # 不要它填通報單，只要它描述畫面
    # 「風險評級」只能以禁止的形式出現，不能是要它填的欄位
    assert "不要提到任何警報或風險評級" in prompt


def test_prompt_要的是客觀描述():
    client = FakeVlmClient(["報告"])
    make_vlm_node(client, max_retries=2)({"alert": ALERT, "image_path": "/img.jpg"})

    prompt = client.calls[0]["prompt"]
    assert "實際看得見" in prompt
    assert "身體姿態" in prompt
    assert "畫面品質" in prompt         # 看不清楚要能說出來，judge 才有機會判 uncertain


# ── 多圖（時序判讀）──────────────────────────────────────
def test_多張連續畫面一起送給_VLM():
    # 單張分不出「躺著休息」與「跌倒」，姿態隨時間的變化才是關鍵
    client = FakeVlmClient(["報告"])
    node = make_vlm_node(client, max_retries=2)

    node({"alert": ALERT, "image_path": "/a.jpg",
          "image_paths": ["/a.jpg", "/b.jpg", "/c.jpg"]})

    assert client.calls[0]["image_path"] == ["/a.jpg", "/b.jpg", "/c.jpg"]
    assert "連續畫面" in client.calls[0]["prompt"]
    assert "隨時間變化" in client.calls[0]["prompt"]


def test_沒有連續畫面時退回單張():
    client = FakeVlmClient(["報告"])
    node = make_vlm_node(client, max_retries=2)

    node({"alert": ALERT, "image_path": "/a.jpg"})

    assert client.calls[0]["image_path"] == "/a.jpg"
    assert "連續畫面" not in client.calls[0]["prompt"]


def test_client_多張圖全部傳給模型():
    fake = FakeOllama(response={"message": {"content": "報告"}})
    client = OllamaVlmClient("qwen2.5vl:7b", "http://localhost:11434", timeout=5)
    client._client = fake

    client.analyze(["/a.jpg", "/b.jpg"], "prompt")

    assert fake.kwargs["messages"][0]["images"] == ["/a.jpg", "/b.jpg"]


def test_client_空清單丟_VlmError():
    client = OllamaVlmClient("qwen2.5vl:7b", "http://localhost:11434", timeout=5)
    client._client = FakeOllama(response={"message": {"content": "報告"}})

    with pytest.raises(VlmError, match="沒有提供任何圖檔"):
        client.analyze([], "prompt")


# ── OllamaVlmClient（碰外部那層）────────────────────────
class FakeOllama:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def chat(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def test_client_取出回應內容():
    client = OllamaVlmClient("llava:latest", "http://localhost:11434", timeout=5)
    client._client = FakeOllama(response={"message": {"content": "  報告內容  "}})

    assert client.analyze("/img.jpg", "prompt") == "報告內容"


def test_client_把圖檔路徑傳給模型():
    fake = FakeOllama(response={"message": {"content": "報告"}})
    client = OllamaVlmClient("llava:latest", "http://localhost:11434", timeout=5)
    client._client = fake

    client.analyze("/imgs/a.jpg", "prompt")

    assert fake.kwargs["model"] == "llava:latest"
    assert fake.kwargs["messages"][0]["images"] == ["/imgs/a.jpg"]


def test_client_逾時轉成_VlmError():
    # 逾時、連不上、模型不存在對節點沒差別，一律是「這次沒拿到判讀」
    client = OllamaVlmClient("llava:latest", "http://localhost:11434", timeout=5)
    client._client = FakeOllama(error=TimeoutError("timed out"))

    with pytest.raises(VlmError, match="Ollama 呼叫失敗"):
        client.analyze("/img.jpg", "prompt")


@pytest.mark.parametrize("response", [
    {"message": {"content": ""}},
    {"message": {"content": "   "}},
    {"message": {}},
    {},
])
def test_client_空回應轉成_VlmError(response):
    client = OllamaVlmClient("llava:latest", "http://localhost:11434", timeout=5)
    client._client = FakeOllama(response=response)

    with pytest.raises(VlmError):
        client.analyze("/img.jpg", "prompt")

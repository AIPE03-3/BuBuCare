"""VLM 推論 client — 把「呼叫 VLM 模型」這個動作與呼叫方(vlm_worker / 未來的 agent)解耦。

為什麼要這層(介面隔離):
依最新系統流程,第 2 層會加入 LangGraph agent + Uncertainty Router,由 agent 決定
「何時呼叫 VLM、帶什麼 system prompt、灰區如何分流」。那些是「觸發/路由」邏輯,屬 agent。
而「把影像+prompt 送給 VLM 模型、拿回文字」這個「推論呼叫點」不管由誰觸發(現在的
Kafka worker、還是未來的 agent)都必須存在、介面不變。

把這個呼叫點抽成獨立 class,好處:
  - 現在 vlm_worker.py 只需呼叫 VLMModel.infer(prompt, image_path)，不必知道後端是誰。
  - 未來 agent 直接 import 同一個 VLMModel,觸發邏輯歸 agent、推論後端現成。
  - 之後要把後端從 Ollama 換成 Triton(TensorRT-LLM / vLLM backend)時,只改本檔內部,
    呼叫方一行都不用動。

後端目前 = 本地 Ollama(依決策 VLM 先留 Ollama、不真的搬 Triton)。介面刻意設計成
後端無關,換 Triton 時新增一個 backend 分支即可。
"""
import os

VLM_BACKEND = os.environ.get("VLM_BACKEND", "ollama")  # 之後可加 "triton"
VLM_MODEL_NAME = os.environ.get("VLM_MODEL_NAME", "llava:latest")


class VLMModel:
    """VLM 推論介面。呼叫方只依賴 `infer(prompt, image_path) -> str`,不依賴後端實作。

    後端由環境變數 `VLM_BACKEND` 選擇(預設 "ollama")。未來把 Qwen2.5-VL 搬上 Triton 時,
    在 `infer` 內加一個 backend=="triton" 分支(打 Triton 的 VLM 服務),介面不變。
    """

    def __init__(self, backend: str = VLM_BACKEND, model_name: str = VLM_MODEL_NAME):
        self._backend = backend
        self._model_name = model_name
        if backend == "ollama":
            import ollama  # 延後 import,讓沒裝 ollama 的環境(如未來純 Triton)也能 import 本模組
            self._ollama = ollama
        else:
            raise ValueError(f"未知的 VLM_BACKEND: {backend}（目前支援 'ollama'；'triton' 待實作）")

    def infer(self, prompt: str, image_path: str) -> str:
        """對單張影像 + system/task prompt 做一次 VLM 推論,回傳判讀文字。

        Args:
            prompt: 完整的指示文字(system + task,由呼叫方依任務 A/B/C 組好)。
            image_path: 影像檔路徑(VLM 讀圖用)。

        Returns:
            VLM 產出的判讀文字(已 strip)。後端失敗時由呼叫方負責處理例外
            (不在此吞掉,讓 worker/agent 能決定降級或重試)。
        """
        if self._backend == "ollama":
            response = self._ollama.chat(
                model=self._model_name,
                messages=[{"role": "user", "content": prompt, "images": [image_path]}],
            )
            return response["message"]["content"].strip()
        raise ValueError(f"未知的 VLM_BACKEND: {self._backend}")

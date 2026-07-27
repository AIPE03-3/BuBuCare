# agent/nodes/vlm.py
"""vlm_analyze 節點：呼叫地端 Ollama 視覺模型判讀快照。

Agent 架構下 VLM 從主角降為工具：它只負責「描述看到什麼」，
判定是 true_alarm 還是 false_alarm 是 judge 節點的工作。

分層：
- OllamaVlmClient 只做一次呼叫（碰外部）
- 節點負責重試與逾時政策（純流程，可單測）
重試耗盡不丟例外——留白的 vlm_report 交給 judge 降級處理，consumer 不中斷。
"""
import logging
import time

from agent.prompts import build_vlm_review_prompt
from agent.schemas import AgentState

logger = logging.getLogger("agent.vlm")


class VlmError(Exception):
    # VLM 呼叫失敗（連不上、逾時、回傳空內容）
    pass


class OllamaVlmClient:
    """薄薄一層包住 ollama.chat：唯一碰外部服務的地方，測試一律注入假的替身。"""

    def __init__(self, model: str, base_url: str, timeout: float):
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self._client = None

    @property
    def client(self):
        # lazy import：沒真的要呼叫模型時，單測不必裝 ollama 也不必連服務
        if self._client is None:
            from ollama import Client

            self._client = Client(host=self.base_url, timeout=self.timeout)
        return self._client

    def analyze(self, image_path: str | list[str], prompt: str) -> str:
        """吃單張或多張圖。多張時依序傳入，代表同一台攝影機的連續畫面。

        單張靜態畫面分不出「躺著休息」與「跌倒」——時序才是關鍵資訊，
        邊緣端的 Action Transformer 就是吃 30 frame 窗口在做這件事。
        """
        images = [image_path] if isinstance(image_path, str) else list(image_path)
        if not images:
            raise VlmError("沒有提供任何圖檔")

        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt, "images": images}],
            )
        except Exception as e:
            # 逾時、連線失敗、模型不存在對節點來說沒差別，一律是「這次沒拿到判讀」
            raise VlmError(f"Ollama 呼叫失敗（model={self.model}）：{e}") from e

        content = (response.get("message", {}) or {}).get("content", "") or ""
        content = content.strip()
        if not content:
            raise VlmError("VLM 回傳空內容")
        return content


def analyze_with_retry(client, image_path: str, prompt: str, max_retries: int) -> tuple[str | None, str | None]:
    """呼叫 VLM，失敗最多重試 max_retries 次。回傳 (報告, 錯誤訊息)，兩者必有一個是 None。

    抽成獨立純流程函式：重試次數、失敗訊息這些行為要能被單測釘死，
    不必為了測「重試兩次」而去戳 LangGraph。
    """
    attempts = max_retries + 1  # max_retries=2 表示「首次 + 重試 2 次」＝ 共 3 次
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            started = time.time()
            report = client.analyze(image_path, prompt)
            logger.info("VLM 判讀完成（第 %d 次嘗試，耗時 %.1fs）", attempt, time.time() - started)
            return report, None
        except VlmError as e:
            last_error = str(e)
            logger.warning("VLM 第 %d/%d 次嘗試失敗：%s", attempt, attempts, last_error)
    return None, last_error


def make_vlm_node(client, max_retries: int):
    def vlm_analyze(state: AgentState) -> dict:
        alert = state["alert"]
        # image_paths 有值代表拿到同一事件的連續畫面（時序判讀）；否則退回單張
        images = state.get("image_paths") or state["image_path"]
        count = len(images) if isinstance(images, list) else 1
        # followup 有值代表是 judge 判 uncertain 後回頭補問，prompt 會多帶追問段落
        prompt = build_vlm_review_prompt(alert, followup=state.get("followup"), image_count=count)
        report, error = analyze_with_retry(client, images, prompt, max_retries)

        if report is None:
            # 沒拿到判讀不算致命：judge 會因為缺證據而降級成「交回人工」
            logger.error("VLM 重試耗盡，交回人工：%s", error)
            return {"vlm_report": None, "vlm_retries": state.get("vlm_retries", 0) + 1}

        return {"vlm_report": report, "vlm_retries": state.get("vlm_retries", 0) + 1}

    return vlm_analyze


def build_vlm_client(settings) -> OllamaVlmClient:
    return OllamaVlmClient(
        model=settings.vlm_model,
        base_url=settings.ollama_base_url,
        timeout=settings.vlm_timeout_seconds,
    )

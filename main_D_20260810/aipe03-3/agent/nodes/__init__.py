# agent/nodes/
# LangGraph 的節點，每個節點一檔。
# 設計原則：LLM 節點只做判斷，副作用（Kafka、檔案）集中在純函式節點（ingest / publish）。

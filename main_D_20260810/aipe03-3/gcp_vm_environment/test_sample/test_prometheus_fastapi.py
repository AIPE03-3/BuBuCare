'''copy 1.'''
from fastapi import FastAPI, Response
from prometheus_client import Counter, generate_latest, CONTENT_TYPE_LATEST
import httpx
import asyncio
import datetime
''' copy 1 end.'''

app = FastAPI()

''' copy 2. '''
#1.定義自訂的 Prometheus Counter 指標
NEGATIVE_HARD_COUNTER = Counter(
    'negative_hard_total', 
    'Total number of times /api/negtive-hard was called'
)
''' copy 2 end.'''

#3.每呼叫一次，指標就 +1
@app.get("/api/negtive-hard")
def negative_hard():
    ''' copy 3. '''
    NEGATIVE_HARD_COUNTER.inc()  # 指標自增 1
    ''' copy 3 end.'''
    return {"message": "negative-hard counter increased by 1"}

''' copy 4. '''
#2.提供給 Prometheus 抓取 NEGATIVE_HARD_COUNTER 資料的, 它只認這個路徑 "/metrics"
@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

#提供給前端查詢 Prometheus 當天所有指標值的 Dashboard API, Docker 內網的寫法:
PROMETHEUS_URL = "http://prometheus:9090"

@app.get("/api/dashboard")
async def get_dashboard_metrics():
    
    # 1. 計算今天從半夜 00:00 到現在過了多少秒
    now = datetime.datetime.now()
    today_start = datetime.datetime.combine(now.date(), datetime.time.min)
    seconds_since_midnight = int((now - today_start).total_seconds())
    
    # 為了避免極端情況（例如剛好半夜 00:00:05 呼叫，時間區間太短 Prometheus 會報錯）
    # 我們設定一個最小區間為 60 秒
    if seconds_since_midnight < 60:
        seconds_since_midnight = 60
        
    # 2. 將秒數轉換為 Prometheus 接受的時間格式字串（例如 "43200s"）
    time_range_str = f"{seconds_since_midnight}s"
    
    # 3. 定義我們要提供給前端的 PromQL 查詢字典
    # 使用 rate([5m]) 算過去 5 分鐘每秒平均速率，這是最適合 Dashboard 的即時指標
    queries = {
        "fastapi_negative_hard_today": f"increase(negative_hard_total[{time_range_str}])",
        
        # 在time_range_string 秒數的區間內 的進入的總message 數(加總)
        "kafka_all_topics_messages_today":  f'sum(increase(kafka_server_brokertopicmetrics_messagesin_total{{topic!=""}}[{time_range_str}])) by (topic)',
        # 根據topic 做分群, 把每個節點的值加總, 計算5分鐘內的平均流入的 每秒bytes
        "kafka_bytes_in_per_sec": 'sum(rate(kafka_server_brokertopicmetrics_bytesin_total{topic!=""}[5m])) by (topic)',
        # 根據topic 做分群, 把每個節點的值加總, 計算5分鐘內的平均流出的 每秒bytes
        "kafka_bytes_out_per_sec": 'sum(rate(kafka_server_brokertopicmetrics_bytesout_total{topic!=""}[5m])) by (topic)',
        # kafka 無法使用的 分區(partition) 數量, 正常應該要永遠為0 
        "kafka_offline_partitions": "kafka_controller_kafkacontroller_offlinepartitionscount"
        
        #"kafka_bytes_out_per_sec": 'rate(kafka_server_brokertopicmetrics_bytesout_total[5m])',
        #"kafka_bytes_in_per_sec": 'rate(kafka_server_brokertopicmetrics_bytesin_total[5m])',
    }
    
    dashboard_data = {}
    current_time = datetime.datetime.now().isoformat()
    
    async with httpx.AsyncClient() as client:
        # 使用 asyncio.gather 同時發出多個查詢，優化後端 API 的反應速度
        tasks = []
        for name, query_expr in queries.items():
            tasks.append(
                client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query_expr})
            )
            
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 解析 Prometheus 回傳的結果
        for (name, _), response in zip(queries.items(), responses):
            if isinstance(response, Exception):
                dashboard_data[name] = {"status": "error", "message": str(response)}
                continue
                
            if response.status_code == 200:
                res_json = response.json()
                results = res_json.get("data", {}).get("result", [])
                
                # 精簡化 Prometheus 的回傳格式，方便前端直接使用
                parsed_metrics = []
                for item in results:
                    metric_info = item.get("metric", {}) # 包含 topic, instance 等標籤
                    value_info = item.get("value", [])   # [timestamp, "value"]
    
                    raw_value = value_info[1] if len(value_info) > 1 else "0" 
                    
                    # Prometheus 的 increase() 函數是基於外插法（Extrapolation）計算的估算值，
                    # 得到的浮點數可能會有小數點（例如 3.00002），
                    # 為了前端 Dashboard 好看，如果是今天自訂的計數器，我們幫它做四捨五入取整數。
                    try:
                        raw_value = str(round(float(raw_value)))
                    except ValueError:
                        pass
                    
                    parsed_metrics.append({
                        "labels": metric_info,
                        "value": raw_value
                    })
                
                dashboard_data[name] = {
                    "status": "success",
                    "data": parsed_metrics
                }
            else:
                dashboard_data[name] = {"status": "error", "message": f"Prometheus HTTP {response.status_code}"}

    return {
        "requested_at": current_time,
        "dashboard": dashboard_data
    }
''' copy 4 end.'''


#新增列出所有指標的 API
@app.get("/api/prometheus-catalog")
async def get_prometheus_catalog():
    """
    讓開發者可以用 curl 快速查看目前 Prometheus 內蒐集了哪些指標名稱
    """
    async with httpx.AsyncClient() as client:
        try:
            # 查詢內建標籤 __name__ 的所有可能值，這就是所有指標的清單
            response = await client.get(f"{PROMETHEUS_URL}/api/v1/label/__name__/values")
            
            if response.status_code == 200:
                res_json = response.json()
                metrics_list = res_json.get("data", [])
                
                return {
                    "status": "success",
                    "total_metrics_count": len(metrics_list),
                    "metrics": metrics_list
                }
            else:
                return {
                    "status": "error",
                    "message": f"Prometheus returned HTTP {response.status_code}"
                }
        except Exception as e:
            return {"error": f"Failed to connect to Prometheus: {str(e)}"}


@app.get("/api")
def read_root():
    return {"status": "FastAPI is running!"}
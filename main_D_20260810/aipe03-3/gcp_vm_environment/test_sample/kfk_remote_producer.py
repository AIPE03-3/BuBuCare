# remote_producer.py (在外網本地端執行)
from kafka import KafkaProducer
import json

GCP_VM_IP = "XXX.XXX.XXX.XXX"
KAFKA_USER = "XXXX...."
KAFKA_PASSWORD = "XXXXX..."
PORT = "XX.."

try:
    producer = KafkaProducer(
        bootstrap_servers=[f"{GCP_VM_IP}:PORT"],
        security_protocol="SASL_PLAINTEXT",
        sasl_mechanism="PLAIN",
        sasl_plain_username=KAFKA_USER,
        sasl_plain_password=KAFKA_PASSWORD,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
        
        #enable_idempotence=True # 開啟冪等性防護,Kafka 會幫您的 Producer 編號。
                                 # 即使重送，Kafka 一看編號就知道「這筆我拿過了」，會直接忽略重複的訊息。
    )
    
    data = {"message": "Hello from external producer!"}
    future = producer.send('test-topic', value=data)
    result = future.get(timeout=60)
    print(f"密碼驗證成功！訊息成功送出到外網，Topic: {result.topic}, Partition: {result.partition}")
except Exception as e:
    print(f"連線或發送失敗: {e}")
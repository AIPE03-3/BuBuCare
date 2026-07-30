(1) GCP VM 型號: e2-standard-2/ 硬碟: 50GB   
GCP 須設定 Firewall (http, ssh, kafka)  
project 資料夾: /var/project  
python tool:uv  

安裝:  
<b>升級到 Node.js 20.x 或 22.x</b>;  <b>rsync</b>;  <b>uv</b>
```
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt update
sudo apt-get install -y nodejs
sudo apt install -y rsync

curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env 
```

(2) VM 路徑配置和對應掛載
<pre>
	/var/project/  
	│  
	├── docker-compose.yml  .env)  
	├── .env (kafka 的帳密; AWS的操作S3的key組, 給compose內的對應設定使用)  
	│  
	├── kafka/  
	│   ├── config/  
	│   │   ├── jmx_prometheus_javaagent.jar　:　/jmx-exporter/xxx  
	│   │   └── jmx_prometheus_kafka.yml　　　:　/jmx-exporter/xxx  
	│   ├── data/　　　　　　　　　　　　　     :　/bitnami/kafka  
	│   └── logs/  
	│  
	├── prometheus/  
	│   ├── config/  
	│   │   └── prometheus.yml　　　　　　　　　:　/etc/prometheus/prometheus.yml  
	│   ├── data/　　　　　　　　　　　　　　　　:　/prometheus  
	│   └── rules/                            :　/etc/prometheus/rules  
	│  
	├── nginx/  
	│   ├── conf/  
	│   │   └── nginx.conf                    : /etc/nginx/nginx.conf  
	│   ├── conf.d/                           : /etc/nginx/conf.d  
	│   │   └── default.conf  
	│   ├── html/                             : /usr/share/nginx/html  
	│   ├── ssl/                              : /etc/nginx/ssl  
	│   └── logs/                             : /var/log/nginx  
	│  
	│  
	├── python                                 : /project  
		└── 未來的module/ (例如:test) 
</pre>
<br><br>
**\* docker compose yml 補充:**  
**restart: always** 的詳細行為：
- 運作機制重點無限重啟：當 Container 崩潰（Crash）時，Docker 會無條件自動將其重啟。
- 啟動延遲遞增：如果容器連續不斷地 Crash，為了避免主機資源被耗盡，Docker 會逐漸增加重啟的間隔時間（例如從幾秒漸增至幾分鐘）。
- 手動停止例外：只有一種情況它不會自動重啟，那就是您明確執行了 docker stop 或 docker-compose down 指令。

| **策略設定** | **Crash 時是否重啟？** | **Docker 服務重啟時是否重啟？** | **說明** |
| --- | --- | --- | --- |
| `no` | ❌ 否 | ❌ 否 | 預設值，容器異常終止後不會自動重啟。 |
| `always` | ✔️ 是 | ✔️ 是 | 無論原因始終重啟。若手動停止，需重啟 Docker 或手動啟動容器來解除。 |
| `unless-stopped` | ✔️ 是 | ✔️ 是 | 與 `always` 類似，但若手動執行過 `docker stop`，則即使重啟 Docker 也不會自動啟動它。 |

(3) git action 會以ubuntu 登入, deploy_dev.sh 放置 /home/ubuntu/ 下

| `on-failure` | ✔️ 是 (僅限非正常退出) | ❌ 否 | 只有在 Exit Code 不為 0（即發生錯誤退出）時才會重啟。 |

(4) 
2026/7/31 add:Grafana, NetData, prometheus postgresql-exporter  
prometheus.conf_netdata_go.d -> netdata go.d/prometheus.conf  
postgres.conf_netdata_go.d -> netdata go.d/postgres.conf

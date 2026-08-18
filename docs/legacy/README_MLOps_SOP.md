# 🚀 AIPE03 專題 - MLOps 全自動化操作指南 (SOP)

這份文件是專為本系統設計的「白話文操作手冊」。
本專題的架構分為 **「冷啟動 (第一次訓練)」** 與 **「系統上線 (主動學習)」** 兩個階段，請依據您的情境執行對應的腳本。

---

## 📌 情境 A：第一次訓練 (Cold Start 冷啟動)
**適用時機**：剛從 Roboflow 下載一大包已經有 `.txt` 標籤的開源資料，想要讓模型具備最基礎的辨識能力。

### 步驟 1：放置資料
請將下載下來的照片與標籤，**全部集中**（不須理會原本的 train/val 切分）丟進以下對應資料夾：
- **物件偵測 (RT-DETR)**：
  - 照片丟進 `Fall/active_learning_dataset/images/`
  - `.txt` 丟進 `Fall/active_learning_dataset/labels/`
- **骨架辨識 (YOLO-Pose)**：
  - 照片丟進 `Fall/active_learning_pose_dataset/images/`
  - `.txt` 丟進 `Fall/active_learning_pose_dataset/labels/`

### 步驟 2：啟動訓練腳本
打開終端機 (Terminal)，依據您的模型執行對應腳本：

```bash
# 訓練 RT-DETR 物件偵測
python Fall/tools/clearml_train_pipeline.py

# 訓練 YOLO-Pose 骨架辨識
python Fall/tools/clearml_pose_train_pipeline.py
```

💡 **這個腳本在背後做了什麼？**
1. **平衡抽樣**：它會自動掃描您的資料，將稀有類別均勻地以 80/20 比例完美切分成 Train 和 Valid，不會污染原始資料。
2. **雲端訓練**：產出專屬的 YAML 檔，並在 ClearML 上開始訓練。
3. **打擂台防護**：訓練完畢後，它會自動發送 Discord 通知給您報捷。

---

## 📌 情境 B：系統正式上線 (主動學習 Data Flywheel)
**適用時機**：模型已經佈署在病房攝影機上，隨時會捕捉到沒有標籤的「全新照片」。我們需要開啟 24 小時巡邏與回傳機制。

請開啟 **兩個** 獨立的終端機視窗來配合操作：

### 終端機 1 號：開啟 24 小時巡邏保全 (絕對不要關閉)
開機後，請輸入以下指令並讓它在背景一直跑：
```bash
python Fall/tools/watchdog.py
```

💡 **這個腳本在背後做了什麼？**
它是 24 小時常駐的鬧鐘。每 5 分鐘會自動幫您執行一次 SDK (`inference_to_labelstudio_sdk.py`)。它會捕捉攝影機拍到的新照片，利用現在的模型畫上 **AI 預標註草稿**，然後自動上傳到 Label Studio 網頁。您只要去網頁上把畫歪的框框修好，按下 Submit 就好！

---

### 終端機 2 號：隨叫隨到的重訓指揮官 (按鈕觸發)
當您在 Label Studio 網頁上累積標註了好幾天的新照片，覺得「是時候讓模型進化了」，請打開第二個終端機輸入：

```bash
python Fall/tools/clearml_train_pipeline.py
```

💡 **這個腳本在背後做了什麼？**
它會把您硬碟裡 **「情境 A 的所有舊照片」＋「這幾天剛標好的新照片」** 混在一起，重新執行 80/20 平衡切分。最聰明的是，它會去雲端下載您上一次的「冠軍模型」來繼承記憶，訓練完後再自己跟自己打擂台，贏了才讓新模型上線！

---

## 💡 常見問題與澄清
* **Q: 從 Roboflow 下載的資料要上傳 Label Studio 嗎？**
  * A: **不用！** 已經有 `.txt` (標準答案) 的資料直接丟進資料夾給 ClearML 訓練就好。Label Studio 只用來對付那些「攝影機拍到、還沒人標註過的新照片」。
* **Q: 如果電腦關機重開，資料會不見嗎？需要重頭來嗎？**
  * A: **不會！** 照片都存在本地硬碟裡。重開機後，您只要重新執行 `python Fall/tools/watchdog.py`，系統就會繼續無縫接軌，收集到的照片也會繼續疊加，越積越多。

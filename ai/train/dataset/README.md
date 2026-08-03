# AcT 重訓資料集

來源：CAUCAFall（10 受試者 × 10 動作 = 100 支）＋ 其水平鏡像（100 支）。
規格：720×480 / 20fps。整併與切分由 `ai/train/build_dataset.py` 產生。

## 目錄

```
dataset/
├── README.md          ← 本檔
├── splits.json        ← 切分定義（訓練腳本讀這份）
├── FLIP_MANIFEST.md   ← 鏡像檔的來源對照
└── videos/            ← 全部影片，扁平存放
```

標籤從檔名前綴取得（`Fall*` = 跌倒、其餘 = 正常），
沿用 `ai/batch_eval.py` 的 `classify_video()`，不需要目錄結構。

幀級標註（跌落起訖）之後請放 `dataset/labels/<影片檔名>.txt`，
格式見 `ai/local_pipeline_eval.py` 的 `parse_label_file()`。

## ⚠ 兩條鐵則

1. **`S<n+10>` 與 `S<n>` 是同一個人**（鏡像），必須在同一個 split。拆開放會造成測試集洩漏，而且從指標上看不出來。
2. **只有訓練集使用鏡像增強。** 驗證集與測試集必須維持原始分布，因此 50 支鏡像檔被列入 `splits.json` 的 `excluded`，不得使用。

## 切分

| split | 受試者 | 支數 | 說明 |
|---|---|---:|---|
| train | [1, 3, 4, 6, 7] ＋其鏡像 | 100 | 原始 50＋鏡像 50 |
| val | [8, 9] | 20 | 不增強 |
| test | [2, 5, 10] | 30 | 不增強。選這三位是因為原 `ai/test_demo/` 的基準影片全落在此，含全部 4 支跌倒基準 |
| （排除） | val/test 的鏡像 | 50 | 不得使用 |

改切分：改 `ai/train/build_dataset.py` 的 `SPLIT_SUBJECTS` 後重跑，不要搬檔案。

## ⚠ 本目錄不在版控

`.gitignore` 排除 `*.mp4`。這些素材只存在於本機，**請另外備份**。

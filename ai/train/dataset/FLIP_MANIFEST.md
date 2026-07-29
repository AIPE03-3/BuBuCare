# 翻轉資料來源對照

本目錄由 `ai/train/flip_videos.py` 產生，內容是來源影片的**水平鏡像**。

- 受試者編號偏移：+10
- Left/Right 檔名對調：開

## ⚠ 切分資料時的鐵則

**`S<n+offset>` 與 `S<n>` 是同一個人**，切分時必須綁在一起進同一個 split。
把來源放 train、鏡像放 val/test，等於測試集洩漏，而且看數字看不出來。

測試集本來就不該做資料增強——屬於測試集的鏡像檔請直接刪除或不要使用。

## 對照表

| 輸出檔 | 來源檔 |
|---|---|
| `FallBackwardsS11.mp4` | `FallBackwardsS1.mp4` |
| `FallBackwardsS20.mp4` | `FallBackwardsS10.mp4` |
| `FallBackwardsS12.mp4` | `FallBackwardsS2.mp4` |
| `FallBackwardsS13.mp4` | `FallBackwardsS3.mp4` |
| `FallBackwardsS14.mp4` | `FallBackwardsS4.mp4` |
| `FallBackwardsS15.mp4` | `FallBackwardsS5.mp4` |
| `FallBackwardsS16.mp4` | `FallBackwardsS6.mp4` |
| `FallBackwardsS17.mp4` | `FallBackwardsS7.mp4` |
| `FallBackwardsS18.mp4` | `FallBackwardsS8.mp4` |
| `FallBackwardsS19.mp4` | `FallBackwardsS9.mp4` |
| `FallForwardS11.mp4` | `FallForwardS1.mp4` |
| `FallForwardS20.mp4` | `FallForwardS10.mp4` |
| `FallForwardS12.mp4` | `FallForwardS2.mp4` |
| `FallForwardS13.mp4` | `FallForwardS3.mp4` |
| `FallForwardS14.mp4` | `FallForwardS4.mp4` |
| `FallForwardS15.mp4` | `FallForwardS5.mp4` |
| `FallForwardS16.mp4` | `FallForwardS6.mp4` |
| `FallForwardS17.mp4` | `FallForwardS7.mp4` |
| `FallForwardS18.mp4` | `FallForwardS8.mp4` |
| `FallForwardS19.mp4` | `FallForwardS9.mp4` |
| `FallRightS11.mp4` | `FallLeftS1.mp4` |
| `FallRightS20.mp4` | `FallLeftS10.mp4` |
| `FallRightS12.mp4` | `FallLeftS2.mp4` |
| `FallRightS13.mp4` | `FallLeftS3.mp4` |
| `FallRightS14.mp4` | `FallLeftS4.mp4` |
| `FallRightS15.mp4` | `FallLeftS5.mp4` |
| `FallRightS16.mp4` | `FallLeftS6.mp4` |
| `FallRightS17.mp4` | `FallLeftS7.mp4` |
| `FallRightS18.mp4` | `FallLeftS8.mp4` |
| `FallRightS19.mp4` | `FallLeftS9.mp4` |
| `FallLeftS11.mp4` | `FallRightS1.mp4` |
| `FallLeftS20.mp4` | `FallRightS10.mp4` |
| `FallLeftS12.mp4` | `FallRightS2.mp4` |
| `FallLeftS13.mp4` | `FallRightS3.mp4` |
| `FallLeftS14.mp4` | `FallRightS4.mp4` |
| `FallLeftS15.mp4` | `FallRightS5.mp4` |
| `FallLeftS16.mp4` | `FallRightS6.mp4` |
| `FallLeftS17.mp4` | `FallRightS7.mp4` |
| `FallLeftS18.mp4` | `FallRightS8.mp4` |
| `FallLeftS19.mp4` | `FallRightS9.mp4` |
| `FallSittingS11.mp4` | `FallSittingS1.mp4` |
| `FallSittingS20.mp4` | `FallSittingS10.mp4` |
| `FallSittingS12.mp4` | `FallSittingS2.mp4` |
| `FallSittingS13.mp4` | `FallSittingS3.mp4` |
| `FallSittingS14.mp4` | `FallSittingS4.mp4` |
| `FallSittingS15.mp4` | `FallSittingS5.mp4` |
| `FallSittingS16.mp4` | `FallSittingS6.mp4` |
| `FallSittingS17.mp4` | `FallSittingS7.mp4` |
| `FallSittingS18.mp4` | `FallSittingS8.mp4` |
| `FallSittingS19.mp4` | `FallSittingS9.mp4` |
| `HopS11.mp4` | `HopS1.mp4` |
| `HopS20.mp4` | `HopS10.mp4` |
| `HopS12.mp4` | `HopS2.mp4` |
| `HopS13.mp4` | `HopS3.mp4` |
| `HopS14.mp4` | `HopS4.mp4` |
| `HopS15.mp4` | `HopS5.mp4` |
| `HopS16.mp4` | `HopS6.mp4` |
| `HopS17.mp4` | `HopS7.mp4` |
| `HopS18.mp4` | `HopS8.mp4` |
| `HopS19.mp4` | `HopS9.mp4` |
| `KneelS11.mp4` | `KneelS1.mp4` |
| `KneelS20.mp4` | `KneelS10.mp4` |
| `KneelS12.mp4` | `KneelS2.mp4` |
| `KneelS13.mp4` | `KneelS3.mp4` |
| `KneelS14.mp4` | `KneelS4.mp4` |
| `KneelS15.mp4` | `KneelS5.mp4` |
| `KneelS16.mp4` | `KneelS6.mp4` |
| `KneelS17.mp4` | `KneelS7.mp4` |
| `KneelS18.mp4` | `KneelS8.mp4` |
| `KneelS19.mp4` | `KneelS9.mp4` |
| `PickupobjectS11.mp4` | `PickupobjectS1.mp4` |
| `PickupobjectS20.mp4` | `PickupobjectS10.mp4` |
| `PickupobjectS12.mp4` | `PickupobjectS2.mp4` |
| `PickupobjectS13.mp4` | `PickupobjectS3.mp4` |
| `PickupobjectS14.mp4` | `PickupobjectS4.mp4` |
| `PickupobjectS15.mp4` | `PickupobjectS5.mp4` |
| `PickupobjectS16.mp4` | `PickupobjectS6.mp4` |
| `PickupobjectS17.mp4` | `PickupobjectS7.mp4` |
| `PickupobjectS18.mp4` | `PickupobjectS8.mp4` |
| `PickupobjectS19.mp4` | `PickupobjectS9.mp4` |
| `SitDownS11.mp4` | `SitDownS1.mp4` |
| `SitDownS20.mp4` | `SitDownS10.mp4` |
| `SitDownS12.mp4` | `SitDownS2.mp4` |
| `SitDownS13.mp4` | `SitDownS3.mp4` |
| `SitDownS14.mp4` | `SitDownS4.mp4` |
| `SitDownS15.mp4` | `SitDownS5.mp4` |
| `SitDownS16.mp4` | `SitDownS6.mp4` |
| `SitDownS17.mp4` | `SitDownS7.mp4` |
| `SitDownS18.mp4` | `SitDownS8.mp4` |
| `SitDownS19.mp4` | `SitDownS9.mp4` |
| `WalkS11.mp4` | `WalkS1.mp4` |
| `WalkS20.mp4` | `WalkS10.mp4` |
| `WalkS12.mp4` | `WalkS2.mp4` |
| `WalkS13.mp4` | `WalkS3.mp4` |
| `WalkS14.mp4` | `WalkS4.mp4` |
| `WalkS15.mp4` | `WalkS5.mp4` |
| `WalkS16.mp4` | `WalkS6.mp4` |
| `WalkS17.mp4` | `WalkS7.mp4` |
| `WalkS18.mp4` | `WalkS8.mp4` |
| `WalkS19.mp4` | `WalkS9.mp4` |

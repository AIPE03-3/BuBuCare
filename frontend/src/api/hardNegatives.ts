import type { HardNegativeItem, HnpLabel } from '../types';
import { hardNegativesMock } from './mock/hardNegatives';

// 後端 Hard Negative 現況為 YOLO 信心自動收集、存檔案系統，無對應 API（04_後端現況與規格落差.md H 段），暫走 mock。
// 介面維持 async 回傳 HardNegativeItem[]，之後只需替換函式內部實作即可接上真實 API。
export async function getHardNegatives(filters?: {
  label?: HnpLabel;
  dateRange?: { from: string; to: string };
}): Promise<HardNegativeItem[]> {
  return hardNegativesMock.filter((item) => {
    if (filters?.label && item.label !== filters.label) return false;
    if (filters?.dateRange) {
      const labeledAt = item.labeled_at;
      if (labeledAt < filters.dateRange.from || labeledAt > filters.dateRange.to) return false;
    }
    return true;
  });
}

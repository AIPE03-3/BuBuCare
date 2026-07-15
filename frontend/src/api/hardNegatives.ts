import type { HardNegativeItem, HnpLabel } from '../types';

// 假資料已移除：Hard Negative 清單回傳空陣列，待後端對應 API 就緒後改為實際呼叫。
export async function getHardNegatives(filters?: {
  label?: HnpLabel;
  dateRange?: { from: string; to: string };
}): Promise<HardNegativeItem[]> {
  void filters; // 保留篩選介面相容；空資料期間不套用，串接後端後改為帶入查詢條件呼叫 API
  return [];
}

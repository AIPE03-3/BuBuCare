import type { FixedTestSet } from '../types';

// 假資料已移除：回傳未凍結的空測試集，待後端對應 API 就緒後改為實際呼叫。
export async function getFixedTestSet(): Promise<FixedTestSet> {
  return {
    is_frozen: false,
    created_at: '',
    composition: [],
    thresholds: [],
  };
}

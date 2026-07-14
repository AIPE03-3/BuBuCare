import type { FixedTestSet } from '../types';
import { fixedTestSetMock } from './mock/fixedTestSet';

// 固定測試集（MLOps 6-7，唯讀）：後端尚無對應 API，本輪全走 mock，
// 介面維持 async 回傳，之後只需替換函式內部實作即可接上真實 API。
export async function getFixedTestSet(): Promise<FixedTestSet> {
  return fixedTestSetMock;
}

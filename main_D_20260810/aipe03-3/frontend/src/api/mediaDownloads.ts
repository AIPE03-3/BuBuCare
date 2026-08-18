import type { DownloadableMedia } from '../types';

// 假資料已移除：影像下載清單回傳空陣列，待後端下載清單 API 就緒後改為實際呼叫。
export async function getDownloadableMedia(): Promise<DownloadableMedia[]> {
  return [];
}

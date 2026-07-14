import type { EnvSafetyScore, EnvHistoryRange } from '../types';

// 聚合粒度（毫秒）：≤24h 原始 15 分級距／1–7 天每小時／>7 天每日（皆取「最低分」非平均，見 03 檔）。
const RAW_STEP_MS = 15 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export function getGranularityMs(range: EnvHistoryRange, spanMs?: number): number {
  if (range === 'today') return RAW_STEP_MS;
  if (range === '7d') return HOUR_MS;
  if (range === '30d') return DAY_MS;
  // custom：>7 天用每日，否則每小時（與 today/7d 一致的門檻）。
  if (spanMs !== undefined && spanMs <= 7 * DAY_MS) return HOUR_MS;
  return DAY_MS;
}

export const AGGREGATION_LABEL: Record<EnvHistoryRange, string> = {
  today: '原始 15 分級距',
  '7d': '每小時最低分',
  '30d': '每日最低分',
  custom: '依區間長度（≤7 天每小時／>7 天每日）最低分',
};

export function getAggregationLabel(range: EnvHistoryRange, spanMs?: number): string {
  if (range !== 'custom') return AGGREGATION_LABEL[range];
  if (spanMs !== undefined && spanMs <= 7 * DAY_MS) return '每小時最低分';
  return '每日最低分';
}

export interface OfflinePeriod {
  from: string; // ISO，離線前最後一筆的時間
  to: string;   // ISO，恢復連線後首筆的時間
}

/**
 * 從聚合後的時間序列推出離線區間：相鄰兩點時間間隔遠大於聚合粒度（> 1.5× 粒度）視為「資料時間洞」＝離線。
 * 離線判斷刻意寫在這裡（util 層），元件只依回傳結果決定圖表虛線斷點與表格合併列，不把邏輯寫死在畫面。
 * points 需已依 assessed_at 由舊到新排序。
 *
 * TODO(待確認 04檔#4)：攝影機故障換新機時，新舊機台目前由前端視為「同一顆延續」（歷史序列連續呈現），
 *   此為前端提案，待後端/產品對 04 檔開放問題 #4 正式拍板；若後端改為獨立實體，需在此處依機台切換切斷序列。
 * TODO(待確認 04檔#5)：暫時離線（offline）與永久已停用（disabled）是否真的在 devices.status 分開存待後端確認；
 *   目前 mock 以「缺資料時間洞」表達暫時離線，disabled 則於選擇器清單排除（見 EnvScoreHistory CameraPicker）。
 */
export function getOfflinePeriods(points: EnvSafetyScore[], granularityMs: number): OfflinePeriod[] {
  const periods: OfflinePeriod[] = [];
  // 以聚合「桶格」為準判斷：連續資料時相鄰兩點必落在相鄰桶（桶索引差 1）；
  // 若中間有一個以上完全空桶（桶索引差 > 1），代表該段查無評分紀錄＝離線。
  // 用桶索引而非時間差，避免每小時/每日粒度下正常資料因代表時間點落點不同被誤判成離線。
  for (let i = 1; i < points.length; i += 1) {
    const prevBucket = Math.floor(new Date(points[i - 1].assessed_at).getTime() / granularityMs);
    const currBucket = Math.floor(new Date(points[i].assessed_at).getTime() / granularityMs);
    if (currBucket - prevBucket > 1) {
      periods.push({ from: points[i - 1].assessed_at, to: points[i].assessed_at });
    }
  }
  return periods;
}

/** 某聚合點是否為「離線後恢復連線的首筆」（無前次可比較，score_drop 應為 null）。 */
export function isReconnectPoint(point: EnvSafetyScore, offlinePeriods: OfflinePeriod[]): boolean {
  return offlinePeriods.some((p) => p.to === point.assessed_at);
}

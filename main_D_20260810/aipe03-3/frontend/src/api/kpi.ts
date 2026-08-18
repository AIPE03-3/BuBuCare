import type { KpiSummary } from '../types';

// 假資料已移除：回傳全 0 摘要，待後端 KPI 端點就緒後改為實際呼叫。
export async function getKpiSummary(): Promise<KpiSummary> {
  return {
    pending_events: 0,
    false_positive_rate: 0,
    hnp_count: 0,
    hnp_threshold: 0,
  };
}

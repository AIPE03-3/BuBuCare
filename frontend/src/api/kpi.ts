import type { KpiSummary } from '../types';
import kpiMock from './mock/kpi.json';

export async function getKpiSummary(): Promise<KpiSummary> {
  return kpiMock;
}

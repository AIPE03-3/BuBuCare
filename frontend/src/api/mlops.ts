import type { EnvHistoryRange, ModelDailyMetric } from '../types';

// 後端 model_daily_metrics 表與 /mlops/metrics 端點尚未建立（04_後端現況與規格落差.md A-7），暫走 mock。
// 介面維持 async 回傳 ModelDailyMetric[]，之後只需替換函式內部實作即可接上真實 API。

const DAY_MS = 24 * 60 * 60 * 1000;
const HISTORY_DAYS = 30;
const PAGE_LOAD_TIME = Date.now();

// 假資料以載入當下為錨點回推 30 天，避免 demo 資料隨時間過去而失真（比照 src/api/envScores.ts 的 PAGE_LOAD_TIME 手法）。
function dayIso(daysAgo: number): string {
  return new Date(PAGE_LOAD_TIME - daysAgo * DAY_MS).toISOString().slice(0, 10);
}

// 簡易決定性亂數（依 seed），確保同一 deviceId 每次重新整理資料形狀一致，方便 demo 展示與驗證分級上色。
function makeRand(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

// 依 deviceId 產生近 30 天序列；null（全域彙總）數值量級較高，單一攝影機較低。
function generateSeries(deviceId: number | null): ModelDailyMetric[] {
  const seed = deviceId ?? 0;
  const rand = makeRand(seed * 7919 + 13);
  const isGlobal = deviceId === null;
  const points: ModelDailyMetric[] = [];

  for (let daysAgo = HISTORY_DAYS - 1; daysAgo >= 0; daysAgo -= 1) {
    const date = dayIso(daysAgo);
    const triggerCount = Math.round((isGlobal ? 40 : 6) + rand() * (isGlobal ? 30 : 8));
    // 刻意讓誤報數涵蓋 0-2／3-5／6+ 三個分級區間，驗證趨勢圖分級上色。
    const cycle = daysAgo % 9;
    const falsePositiveCount =
      cycle < 3 ? Math.round(rand() * 2) : cycle < 6 ? 3 + Math.round(rand() * 2) : 6 + Math.round(rand() * 4);
    const avgConfidence = Math.round((0.72 + rand() * 0.2) * 100) / 100;
    const vlmOverrideRate = Math.round((0.05 + rand() * 0.15) * 100) / 100;
    const hardNegativePoolSize = Math.round((isGlobal ? 120 : 15) + (HISTORY_DAYS - daysAgo) * (isGlobal ? 3 : 0.5));

    points.push({
      id: `mlops-${deviceId ?? 'all'}-${date}`,
      device_id: deviceId,
      date,
      yolo_trigger_count: triggerCount,
      false_positive_count: falsePositiveCount,
      avg_confidence: avgConfidence,
      vlm_override_rate: vlmOverrideRate,
      hard_negative_pool_size: hardNegativePoolSize,
    });
  }

  return points;
}

function rangeToDayCount(range: EnvHistoryRange): number {
  if (range === 'today') return 1;
  if (range === '7d') return 7;
  return HISTORY_DAYS; // '30d' 暫用 30 天窗口；'custom' 另由 filterByCustomRange 篩選
}

// 自訂區間：假資料序列只回推 30 天，故 from/to 超出此窗口的部分自然查無資料（比照真後端「查無紀錄」情境）。
function filterByCustomRange(series: ModelDailyMetric[], from: string, to: string): ModelDailyMetric[] {
  return series.filter((point) => point.date >= from && point.date <= to);
}

export async function getDailyMetrics(params: {
  range: EnvHistoryRange;
  deviceId?: number | null;
  customFrom?: string;
  customTo?: string;
}): Promise<ModelDailyMetric[]> {
  const deviceId = params.deviceId ?? null;
  const series = generateSeries(deviceId);

  if (params.range === 'custom') {
    if (!params.customFrom || !params.customTo) return [];
    return filterByCustomRange(series, params.customFrom, params.customTo);
  }

  const dayCount = rangeToDayCount(params.range);
  return series.slice(-dayCount);
}

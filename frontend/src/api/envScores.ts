import type { EnvScore, EnvSafetyScore, EnvHistoryRange } from '../types';
import rawEnvScores from './mock/envScores.json';
import envScoreHistoryMock from './mock/envScoreHistory.json';
import { getEnvScoreLevel } from '../utils/envScore';
import { getGranularityMs } from '../utils/envOfflinePeriods';

/**
 * mock JSON 存的是相對於載入當下的 days_ago／minutes_ago 偏移量，
 * 讓「近 7 日」「較昨日」「已離線 N 小時 N 分」等 demo 資料不會隨時間過去而失真。
 * 待後端提供正式 env_safety_scores 資料（含 assessed_at）後，此轉換與偏移量欄位一併整段刪除即可。
 */
interface RawEnvScore extends Omit<EnvScore, 'assessed_at'> {
  previous_score?: number;
  offline_minutes_ago?: number;
  history_days_ago: { days_ago: number; score: number }[];
  alerts_days_ago: { days_ago: number; score: number; drop: number }[];
}

export interface EnvScoreAlert {
  date: string;
  score: number;
  drop: number;
}

const PAGE_LOAD_TIME = Date.now();
const DAY_MS = 24 * 60 * 60 * 1000;
const MINUTE_MS = 60 * 1000;

function daysAgoToIso(daysAgo: number): string {
  return new Date(PAGE_LOAD_TIME - daysAgo * DAY_MS).toISOString();
}

function toEnvScore(raw: RawEnvScore): EnvScore {
  const assessed_at = raw.online
    ? daysAgoToIso(raw.history_days_ago[raw.history_days_ago.length - 1]?.days_ago ?? 0)
    : new Date(PAGE_LOAD_TIME - (raw.offline_minutes_ago ?? 0) * MINUTE_MS).toISOString();

  return {
    score_id: raw.score_id,
    camera: raw.camera,
    total_score: raw.total_score,
    dimensions: raw.dimensions,
    level: raw.level,
    overall_description: raw.overall_description,
    risk_factors: raw.risk_factors,
    score_drop: raw.score_drop,
    online: raw.online,
    assessed_at,
  };
}

const RAW_SCORES = rawEnvScores as RawEnvScore[];
const SCORES: EnvScore[] = RAW_SCORES.map(toEnvScore);
const rawById = new Map(RAW_SCORES.map((raw) => [raw.score_id, raw]));

export async function getLatestEnvScores(): Promise<EnvScore[]> {
  return SCORES;
}

export async function getEnvScoreDetail(
  scoreId: string,
): Promise<(EnvScore & { history: { date: string; score: number }[]; alerts: EnvScoreAlert[]; previousScore: number | null }) | null> {
  const score = SCORES.find((s) => s.score_id === scoreId);
  const raw = rawById.get(scoreId);
  if (!score || !raw) return null;

  return {
    ...score,
    history: raw.history_days_ago.map((point) => ({ date: daysAgoToIso(point.days_ago), score: point.score })),
    alerts: raw.alerts_days_ago.map((alert) => ({ date: daysAgoToIso(alert.days_ago), score: alert.score, drop: alert.drop })),
    previousScore: raw.previous_score ?? null,
  };
}

// ── 環境安全評分歷史（IA 7-2）時間序列 ────────────────────────────────────────
// 後端 env_safety_scores 表尚未建立（04 檔 A-6/A-7），本輪由壓縮規格 mock 展開成原始序列再聚合。
// 接真後端時，僅需把 getEnvScoreHistory 內部改為呼叫 GET /env-scores（device_id + 區間），
// 並讓後端回傳已聚合的 EnvSafetyScore[]（或加 granularity 參數，見 04 檔 C-1）。元件不用改。

const HISTORY_LOAD_TIME = Date.now();

interface RawDevicePinned { min_ago_days: number; min_ago_time: number; score: number }
interface RawDeviceDip { from_days_ago: number; to_days_ago: number; score: number }
interface RawDeviceOffline { from_min_ago_days: number; from_min_ago_time: number; to_min_ago_days: number; to_min_ago_time: number }
interface RawHistoryDevice {
  device_id: number;
  base_score: number;
  seed: number;
  offline_periods: RawDeviceOffline[];
  pinned: RawDevicePinned[];
  dips: RawDeviceDip[];
}

const HISTORY = envScoreHistoryMock as { span_days: number; devices: RawHistoryDevice[] };

// min_ago（天 + 當日分鐘）→ 距今分鐘數（越大越舊）。
function toMinutesAgo(days: number, timeMinutes: number): number {
  return days * 24 * 60 + timeMinutes;
}

// 展開單一裝置的原始 15 分級距序列（跳過離線區間內的點），套用 pinned 覆寫與 dips 低分區段。
function expandRawSeries(device: RawHistoryDevice, spanDays: number): { ms: number; score: number }[] {
  let seed = device.seed;
  const rand = () => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
  };
  const offlineWindows = device.offline_periods.map((p) => ({
    fromMinAgo: toMinutesAgo(p.from_min_ago_days, p.from_min_ago_time),
    toMinAgo: toMinutesAgo(p.to_min_ago_days, p.to_min_ago_time),
  }));
  const dipWindows = device.dips.map((d) => ({
    fromMinAgo: d.from_days_ago * 24 * 60,
    toMinAgo: d.to_days_ago * 24 * 60,
    score: d.score,
  }));

  const startMinAgo = spanDays * 24 * 60;
  const points: { ms: number; score: number }[] = [];
  for (let minAgo = startMinAgo; minAgo >= 0; minAgo -= 15) {
    // 離線區間：略過該點（畫面上呈現為缺資料的時間洞，離線判斷由 getOfflinePeriods 從空桶推得）。
    if (offlineWindows.some((w) => minAgo <= w.fromMinAgo && minAgo >= w.toMinAgo)) continue;
    let score = device.base_score + Math.round((rand() - 0.5) * 6);
    for (const dip of dipWindows) {
      if (minAgo <= dip.fromMinAgo && minAgo >= dip.toMinAgo) score = dip.score + Math.round((rand() - 0.5) * 4);
    }
    score = Math.max(0, Math.min(100, score));
    points.push({ ms: HISTORY_LOAD_TIME - minAgo * 60 * 1000, score });
  }

  // pinned：覆寫離線前最後一筆與恢復連線首筆等關鍵點，確保 demo 腳本數值精準。
  for (const pin of device.pinned) {
    const ms = HISTORY_LOAD_TIME - toMinutesAgo(pin.min_ago_days, pin.min_ago_time) * 60 * 1000;
    points.push({ ms, score: pin.score });
  }
  points.sort((a, b) => a.ms - b.ms);
  return points;
}

function rangeToWindow(range: EnvHistoryRange, custom?: { from: string; to: string }): { fromMs: number; toMs: number } {
  const toMs = HISTORY_LOAD_TIME;
  if (range === 'today') return { fromMs: toMs - 24 * 60 * 60 * 1000, toMs };
  if (range === '7d') return { fromMs: toMs - 7 * 24 * 60 * 60 * 1000, toMs };
  if (range === '30d') return { fromMs: toMs - 30 * 24 * 60 * 60 * 1000, toMs };
  return {
    fromMs: custom?.from ? new Date(custom.from).getTime() : toMs - 30 * 24 * 60 * 60 * 1000,
    toMs: custom?.to ? new Date(custom.to).getTime() : toMs,
  };
}

/**
 * 環境安全評分歷史：回傳單一裝置在指定區間、依聚合粒度降採樣（取「最低分」非平均）的逐筆序列。
 * score_drop 為與前一個聚合點的差；離線後恢復首筆（或無前一點）為 null。
 */
export async function getEnvScoreHistory(
  deviceId: number,
  range: EnvHistoryRange,
  custom?: { from: string; to: string },
): Promise<EnvSafetyScore[]> {
  const device = HISTORY.devices.find((d) => d.device_id === deviceId);
  if (!device) return [];

  const raw = expandRawSeries(device, HISTORY.span_days);
  const { fromMs, toMs } = rangeToWindow(range, custom);
  const inWindow = raw.filter((p) => p.ms >= fromMs && p.ms <= toMs);
  const spanMs = toMs - fromMs;
  const granularityMs = getGranularityMs(range, spanMs);

  // 依粒度分桶，每桶取「最低分」，並記下桶索引。離線＝相鄰兩桶索引差 > 1（中間有空桶）。
  const buckets = new Map<number, { bucket: number; ms: number; score: number }>();
  for (const p of inWindow) {
    const bucket = Math.floor(p.ms / granularityMs);
    const existing = buckets.get(bucket);
    if (!existing || p.score < existing.score) {
      buckets.set(bucket, { bucket, ms: p.ms, score: p.score });
    }
  }

  const ordered = [...buckets.values()].sort((a, b) => a.bucket - b.bucket);
  return ordered.map((point, i) => {
    const prev = ordered[i - 1];
    // 無前一點、或與前一點間有空桶（跨越離線區間，即恢復連線首筆）→ 無前次可比較，score_drop=null。
    // 此規則與 getOfflinePeriods 一致（同樣以桶索引差 > 1 判定），確保圖表/表格離線呈現與 null 標記不打架。
    const noPrev = !prev || point.bucket - prev.bucket > 1;
    const score_drop = noPrev ? null : point.score - prev.score;
    return {
      score_id: `env-hist-${deviceId}-${point.ms}`,
      device_id: deviceId,
      total_score: point.score,
      grade: getEnvScoreLevel(point.score),
      score_drop,
      assessed_at: new Date(point.ms).toISOString(),
    };
  });
}

import type { Camera, HardNegativeItem, HnpLabel } from '../../types';
import camerasMock from './cameras.json';

const cameras = camerasMock as Camera[];

const DAY_MS = 24 * 60 * 60 * 1000;
const PAGE_LOAD_TIME = Date.now();

const LABELS: HnpLabel[] = ['坐地', '伸展', '彎腰', '攙扶', '其他'];
const LABELERS = ['王小美', '陳建宏', '林雅婷'];

const NOTES: (string | null)[] = [
  null,
  null,
  '住民自行坐下休息',
  '看護攙扶行走，非跌倒',
  null,
  '伸展運動誤觸警戒區',
];

function daysAgoIso(daysAgo: number, hour: number, minute: number): string {
  const d = new Date(PAGE_LOAD_TIME - daysAgo * DAY_MS);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
}

// 簡易決定性亂數（依 seed），確保 demo 重新整理資料形狀一致（比照 src/api/mlops.ts 的 makeRand 手法）。
function makeRand(seed: number) {
  let s = seed;
  return () => {
    s = (s * 1103515245 + 12345) & 0x7fffffff;
    return s / 0x7fffffff;
  };
}

function generateHardNegatives(): HardNegativeItem[] {
  const rand = makeRand(2026);
  const items: HardNegativeItem[] = [];
  const total = 18;

  for (let i = 0; i < total; i += 1) {
    const camera = cameras[i % cameras.length];
    const label = LABELS[i % LABELS.length];
    const labeledBy = LABELERS[i % LABELERS.length];
    const note = NOTES[i % NOTES.length];
    const daysAgo = Math.floor(rand() * 30);
    const hour = 6 + Math.floor(rand() * 14);
    const minute = Math.floor(rand() * 60);

    items.push({
      id: `hnp-${i + 1}`,
      event_id: `evt-hnp-${i + 1}`,
      camera,
      label,
      note,
      labeled_by: labeledBy,
      labeled_at: daysAgoIso(daysAgo, hour, minute),
      clip_path: `/mock-clips/hnp-${i + 1}.mp4`,
    });
  }

  return items.sort((a, b) => new Date(b.labeled_at).getTime() - new Date(a.labeled_at).getTime());
}

export const hardNegativesMock: HardNegativeItem[] = generateHardNegatives();

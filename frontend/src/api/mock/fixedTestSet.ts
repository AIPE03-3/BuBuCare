import type { FixedTestSet } from '../../types';

export const fixedTestSetMock: FixedTestSet = {
  is_frozen: true,
  created_at: '2026-07-01T09:00:00.000Z',
  composition: [
    { category: '正樣本', count: 120 },
    { category: '坐地', count: 30 },
    { category: '伸展', count: 25 },
    { category: '彎腰', count: 22 },
    { category: '攙扶', count: 18 },
  ],
  thresholds: [
    { metric: 'Recall（召回率）', threshold_text: '≥ 現行 Production 版本' },
    { metric: '誤報率', threshold_text: '< 現行版本 × 1.1' },
    { metric: 'mAP@0.5', threshold_text: '≥ 0.75' },
  ],
};

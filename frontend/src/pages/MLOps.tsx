import { useState } from 'react';
import { DailyMetricsTab } from './mlops/DailyMetricsTab';
import { FixedTestSetTab } from './mlops/FixedTestSetTab';
import { HardNegativePoolTab } from './mlops/HardNegativePoolTab';
import { ModelVersionsTab } from './mlops/ModelVersionsTab';

type MLOpsTab = 'dailyMetrics' | 'hardNegativePool' | 'modelVersions' | 'fixedTestSet';

const TABS: { value: MLOpsTab; label: string }[] = [
  { value: 'dailyMetrics', label: '每日效能指標' },
  { value: 'hardNegativePool', label: 'Hard Negative Pool' },
  { value: 'modelVersions', label: '模型版本管理' },
  { value: 'fixedTestSet', label: '固定測試集' },
];

export function MLOps() {
  const [tab, setTab] = useState<MLOpsTab>('dailyMetrics');

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">MLOps 面板</h1>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={`px-4 py-2 text-sm transition-colors duration-150 ${
              tab === t.value
                ? 'border-b-2 border-[var(--brand)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'dailyMetrics' && <DailyMetricsTab />}
      {tab === 'hardNegativePool' && <HardNegativePoolTab />}
      {tab === 'modelVersions' && <ModelVersionsTab />}
      {tab === 'fixedTestSet' && <FixedTestSetTab />}
    </div>
  );
}

export default MLOps;

import { useEffect, useState } from 'react';
import { getKpiSummary } from '../../api/kpi';
import { getModelVersions, promoteToProduction, rollbackToVersion, triggerManualFineTune } from '../../api/modelVersions';
import { ModelVersionActionModal } from '../../components/ModelVersionActionModal';
import { WarningIcon } from '../../components/icons';
import type { KpiSummary, ModelVersion, ModelVersionStatus } from '../../types';
import { MODEL_VERSION_STATUS_LABEL } from '../../types';

const MODEL_STATUS_STYLE: Record<ModelVersionStatus, string> = {
  staging: 'border border-[var(--text-primary)] text-[var(--text-primary)] bg-transparent',
  production: 'bg-[var(--success-bg)] text-[var(--success)]',
  retired: 'border border-[var(--offline)] text-[var(--offline)] bg-transparent',
};

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function latestRetiredId(versions: ModelVersion[]): string | null {
  const retired = versions.filter((v) => v.status === 'retired');
  if (retired.length === 0) return null;
  return retired.reduce((latest, v) => (v.created_at > latest.created_at ? v : latest)).version_id;
}

interface FineTuneTriggerCardProps {
  kpi: KpiSummary;
  onManualTrigger: () => void;
}

function FineTuneTriggerCard({ kpi, onManualTrigger }: FineTuneTriggerCardProps) {
  const { hnp_count: count, hnp_threshold: threshold } = kpi;
  const triggered = count >= threshold;
  const percent = Math.min(100, (count / threshold) * 100);

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="flex items-center gap-1.5 text-base font-medium text-[var(--text-primary)]">
          {triggered && <WarningIcon aria-hidden="true" className="h-4 w-4 shrink-0 text-[var(--warning)]" />}
          Fine-tune 觸發
        </h2>
        <button
          type="button"
          onClick={onManualTrigger}
          className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150"
        >
          手動觸發
        </button>
      </div>

      <div className="mt-4 flex items-center justify-between text-sm text-[var(--text-secondary)]">
        <span>Hard Negative Pool</span>
        <span>
          {count} / {threshold}
        </span>
      </div>
      <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-[var(--bg-surface-2)]">
        <div
          className={`h-full rounded-full ${triggered ? 'bg-[var(--warning)]' : 'bg-[var(--brand)]'}`}
          style={{ width: `${percent}%` }}
        />
      </div>

      <p className="mt-3 text-xs text-[var(--text-muted)]">
        {triggered
          ? '已達建議觸發門檻，可考慮執行 fine-tune'
          : `尚需 ${Math.max(0, threshold - count)} 筆達建議觸發門檻；亦可依近 7 天誤報趨勢或信心分數下滑提前觸發，門檻非強制。`}
      </p>

      <div className="mt-4 flex items-center gap-2 border-t border-[var(--border)] pt-3">
        <input type="checkbox" disabled checked={false} readOnly />
        <span className="text-sm text-[var(--text-muted)]">自動閾值觸發（尚未開放）</span>
      </div>
    </div>
  );
}

export function ModelVersionsTab() {
  const [kpi, setKpi] = useState<KpiSummary | null>(null);
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [confirmAction, setConfirmAction] = useState<{ mode: 'promote' | 'rollback'; target: ModelVersion } | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    getKpiSummary().then(setKpi);
  }, []);

  useEffect(() => {
    getModelVersions().then(setVersions);
  }, []);

  useEffect(() => {
    if (!toastMessage) return;
    const timer = setTimeout(() => setToastMessage(null), 3000);
    return () => clearTimeout(timer);
  }, [toastMessage]);

  function handleManualTrigger() {
    void triggerManualFineTune();
    setToastMessage('已送出手動訓練請求（mock，尚未實際串接後端）');
  }

  function handleConfirmAction(target: ModelVersion, mode: 'promote' | 'rollback') {
    setVersions((prev) =>
      prev.map((v) => {
        if (v.version_id === target.version_id) {
          return { ...v, status: 'production', deployed_at: new Date().toISOString() };
        }
        if (v.status === 'production') {
          return { ...v, status: 'retired' };
        }
        return v;
      }),
    );
    if (mode === 'promote') void promoteToProduction(target.version_id);
    else void rollbackToVersion(target.version_id);
    setConfirmAction(null);
  }

  const latestRetired = latestRetiredId(versions);

  return (
    <div className="flex flex-col gap-4">
      {kpi && <FineTuneTriggerCard kpi={kpi} onManualTrigger={handleManualTrigger} />}

      <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              <th className="px-3 py-2 font-medium">版本</th>
              <th className="px-3 py-2 font-medium">狀態</th>
              <th className="px-3 py-2 font-medium">Recall</th>
              <th className="px-3 py-2 font-medium">誤報率</th>
              <th className="px-3 py-2 font-medium">mAP@0.5</th>
              <th className="px-3 py-2 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((v) => (
              <tr key={v.version_id} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                <td className="px-3 py-2 text-[var(--text-primary)]">{v.version_tag}</td>
                <td className="px-3 py-2">
                  <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${MODEL_STATUS_STYLE[v.status]}`}>
                    {MODEL_VERSION_STATUS_LABEL[v.status]}
                  </span>
                </td>
                <td className="px-3 py-2 text-[var(--text-primary)]">{formatPercent(v.recall)}</td>
                <td className="px-3 py-2 text-[var(--text-primary)]">{formatPercent(v.false_positive_rate)}</td>
                <td className="px-3 py-2 text-[var(--text-primary)]">{formatPercent(v.map_50)}</td>
                <td className="px-3 py-2">
                  {v.status === 'staging' && (
                    <button
                      type="button"
                      onClick={() => setConfirmAction({ mode: 'promote', target: v })}
                      className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150"
                    >
                      審核並上線
                    </button>
                  )}
                  {v.status === 'production' && <span className="text-[var(--text-secondary)]">目前上線中</span>}
                  {v.status === 'retired' && v.version_id === latestRetired && (
                    <button
                      type="button"
                      onClick={() => setConfirmAction({ mode: 'rollback', target: v })}
                      className="rounded-md border border-[var(--brand)] bg-transparent px-3 py-1 text-sm text-[var(--brand)] transition-colors duration-150"
                    >
                      回滾至此版
                    </button>
                  )}
                  {v.status === 'retired' && v.version_id !== latestRetired && (
                    <span className="text-[var(--text-muted)]">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirmAction && (
        <ModelVersionActionModal
          mode={confirmAction.mode}
          target={confirmAction.target}
          onConfirm={() => handleConfirmAction(confirmAction.target, confirmAction.mode)}
          onCancel={() => setConfirmAction(null)}
        />
      )}

      {toastMessage && (
        <div className="fixed right-6 bottom-6 z-[10000] rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm text-[var(--text-primary)]">
          {toastMessage}
        </div>
      )}
    </div>
  );
}

export default ModelVersionsTab;

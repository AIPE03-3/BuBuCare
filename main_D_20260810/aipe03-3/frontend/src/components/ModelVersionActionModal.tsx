import { createPortal } from 'react-dom';
import type { ModelVersion } from '../types';

interface ModelVersionActionModalProps {
  mode: 'promote' | 'rollback';
  target: ModelVersion;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ModelVersionActionModal({ mode, target, onConfirm, onCancel }: ModelVersionActionModalProps) {
  const title =
    mode === 'promote'
      ? `確認將 ${target.version_tag} 升格為 Production`
      : `確認回滾至 ${target.version_tag}`;

  return createPortal(
    <div className="fixed inset-0 z-[10001] flex items-center justify-center bg-[var(--overlay)] p-6">
      <div className="flex w-[480px] max-w-full flex-col gap-4 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6">
        <h2 className="text-lg font-semibold text-[var(--text-primary)]">{title}</h2>

        {mode === 'promote' ? (
          <div className="flex flex-col gap-1 text-sm text-[var(--text-secondary)]">
            <p>固定測試集門檻（示意）：</p>
            <p>Recall：{(target.recall * 100).toFixed(1)}%</p>
            <p>誤報率：{(target.false_positive_rate * 100).toFixed(1)}%</p>
            <p className="mt-2 text-[var(--text-primary)]">原 production 版本將自動轉為 retired，仍可回滾。</p>
          </div>
        ) : (
          <p className="text-sm text-[var(--text-primary)]">
            目前上線版本將轉為 retired，回滾後線上服務改用 {target.version_tag}。
          </p>
        )}

        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onConfirm}
            className="min-w-0 flex-[2] rounded-md bg-[var(--brand)] px-3 py-2 text-sm font-medium text-white transition-colors duration-150"
          >
            確認
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="min-w-0 flex-1 rounded-md border border-[var(--text-secondary)] bg-transparent px-3 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150"
          >
            取消
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

export default ModelVersionActionModal;

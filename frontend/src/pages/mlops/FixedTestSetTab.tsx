import { useEffect, useState } from 'react';
import { getFixedTestSet } from '../../api/fixedTestSet';
import { LockIcon } from '../../components/icons';
import type { FixedTestSet } from '../../types';
import { formatDate } from '../../utils/time';

export function FixedTestSetTab() {
  const [data, setData] = useState<FixedTestSet | null>(null);

  useEffect(() => {
    getFixedTestSet().then(setData);
  }, []);

  if (!data) return null;

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="text-base font-medium text-[var(--text-primary)]">凍結狀態</h2>
          {data.is_frozen && (
            <div className="mt-3 inline-flex items-center gap-2 rounded-full bg-[var(--brand-soft)] px-3 py-1 text-sm text-[var(--text-primary)]">
              <LockIcon aria-hidden="true" className="h-4 w-4" />
              <span>已凍結</span>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
          <h2 className="text-base font-medium text-[var(--text-primary)]">建立時間</h2>
          <p className="mt-3 text-sm text-[var(--text-primary)]">
            {data.created_at ? formatDate(data.created_at) : '—'}
          </p>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="text-base font-medium text-[var(--text-primary)]">測試集組成</h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
              <tr>
                <th className="px-3 py-2 font-medium">樣本類型</th>
                <th className="px-3 py-2 font-medium">數量</th>
              </tr>
            </thead>
            <tbody>
              {data.composition.map((row) => (
                <tr key={row.category} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                  <td className="px-3 py-2 text-[var(--text-primary)]">{row.category}</td>
                  <td className="px-3 py-2 text-[var(--text-primary)]">{row.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
        <h2 className="text-base font-medium text-[var(--text-primary)]">部署門檻（升格 Production 前須同時通過）</h2>
        <div className="mt-3 overflow-x-auto rounded-xl border border-[var(--border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
              <tr>
                <th className="px-3 py-2 font-medium">指標</th>
                <th className="px-3 py-2 font-medium">門檻</th>
              </tr>
            </thead>
            <tbody>
              {data.thresholds.map((row) => (
                <tr key={row.metric} className="border-t border-[var(--border)] bg-[var(--bg-surface)]">
                  <td className="px-3 py-2 text-[var(--text-primary)]">{row.metric}</td>
                  <td className="px-3 py-2 text-[var(--text-primary)]">{row.threshold_text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default FixedTestSetTab;

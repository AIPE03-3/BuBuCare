import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import type { CareEvent } from '../types';

// 事件清單的欄位定義：一份定義同時餵給桌機表格與手機卡片，避免兩種版型各寫一份而失去同步。
export interface EventListColumn {
  key: string;
  header: string;
  cell: (event: CareEvent, index: number) => ReactNode;
}

// 響應式事件清單：桌機（md 以上）顯示表格，手機顯示堆疊卡片，避免窄螢幕被迫橫向捲動。
// 事件中心、製作通報單、歷史紀錄、誤報紀錄共用同一版型，各頁只需提供欄位定義與點列去向。
export function ResponsiveEventList({
  events,
  columns,
  getRowHref,
  emptyMessage,
}: {
  events: CareEvent[];
  columns: EventListColumn[];
  getRowHref: (event: CareEvent) => string;
  emptyMessage: string;
}) {
  const navigate = useNavigate();

  if (events.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">{emptyMessage}</p>;
  }

  return (
    <>
      {/* 桌機：表格版型 */}
      <div className="hidden overflow-x-auto rounded-xl border border-[var(--border)] md:block">
        <table className="w-full text-left text-sm">
          <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="px-4 py-3 font-medium">
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {events.map((event, index) => (
              <tr
                key={event.id}
                onClick={() => navigate(getRowHref(event))}
                className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
              >
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-3">
                    {col.cell(event, index)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 手機：卡片版型，每欄一行標籤對值，不再橫向捲動 */}
      <ul className="flex flex-col gap-3 md:hidden">
        {events.map((event, index) => (
          <li key={event.id}>
            <button
              type="button"
              onClick={() => navigate(getRowHref(event))}
              className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4 text-left transition-colors duration-150 hover:bg-[var(--brand-soft)]"
            >
              <dl className="flex flex-col gap-2 text-sm">
                {columns.map((col) => (
                  <div key={col.key} className="flex items-start justify-between gap-3">
                    <dt className="shrink-0 text-xs text-[var(--text-muted)]">{col.header}</dt>
                    <dd className="min-w-0 break-words text-right">{col.cell(event, index)}</dd>
                  </div>
                ))}
              </dl>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}

export default ResponsiveEventList;

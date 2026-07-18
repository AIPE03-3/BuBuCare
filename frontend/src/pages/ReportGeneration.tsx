import { EventCenterUnresolved } from './EventCenterUnresolved';

// 製作通報單：列出所有未結案事件，內容與事件中心「未結案」分頁一致（複用同一元件，不重寫）。
// 差異僅在點列去向——這裡導向通報單填寫頁，而非事件詳情頁。
export function ReportGeneration() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">製作通報單</h1>
      <p className="text-sm text-[var(--text-secondary)]">點選任一筆事件開始填寫通報單。</p>
      <EventCenterUnresolved getRowHref={(event) => `/reports/${event.id}`} />
    </div>
  );
}

export default ReportGeneration;

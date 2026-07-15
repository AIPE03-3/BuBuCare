import { EventCenterUnresolved } from './EventCenterUnresolved';

// 生成通報單：列出所有未結案事件，內容與事件中心「未結案」分頁一致（複用同一元件，不重寫）。
export function ReportGeneration() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">生成通報單</h1>
      <EventCenterUnresolved />
    </div>
  );
}

export default ReportGeneration;

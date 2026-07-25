import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { ReportContent } from '../components/ReportContent';
import { getLatestReport } from '../api/reports';
import type { SavedReport } from '../types';

// 讀後端已儲存的通報單，渲染成可列印版面；按「列印／存 PDF」呼叫瀏覽器列印，
// 使用者在列印對話框選「另存為 PDF」即完成輸出（MVP 零外掛，未來可換真匯出模組）。
// 十一段內容交由 ReportContent 呈現（與歷史事件詳情的通報歷程共用同一份版面）。

export function ReportPreview() {
  const { id } = useParams();
  // 通報單走 async api（好換成後端 fetch），effect 載入；loading 與「查無通報單」分開呈現。
  // 路由無 :id（理論上不會發生）時不載入，初始即非 loading → 直接顯示「查無通報單」。
  const [saved, setSaved] = useState<SavedReport | null>(null);
  const [loading, setLoading] = useState(() => Boolean(id));

  useEffect(() => {
    if (!id) return;
    getLatestReport(id).then((record) => {
      setSaved(record);
      setLoading(false);
    });
  }, [id]);

  if (loading) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">載入中…</p>
      </div>
    );
  }

  if (!saved) {
    return (
      <div className="flex flex-col gap-3">
        <BackButton />
        <p className="text-sm text-[var(--text-secondary)]">此事件尚未儲存通報單，無法預覽。</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {/* 控制列：不在 print-area 內，故列印時自動隱藏。 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <BackButton />
        <button
          type="button"
          onClick={() => window.print()}
          className="rounded-md bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90"
        >
          列印／存 PDF
        </button>
      </div>

      <div className="print-area mx-auto w-full max-w-2xl rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 shadow-sm">
        <header className="border-b-2 border-[var(--text-primary)] pb-3 text-center">
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">長照事件通報單</h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">通報別：{saved.form.reportType ?? '—'}</p>
        </header>

        <div className="mt-5">
          <ReportContent form={saved.form} />
        </div>
      </div>
    </div>
  );
}

export default ReportPreview;

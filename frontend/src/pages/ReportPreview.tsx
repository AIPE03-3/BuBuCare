import { useEffect, useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { BackButton } from '../components/BackButton';
import { getLatestReport } from '../api/reports';
import type { ReportFormData, SavedReport } from '../types';

// 讀後端已儲存的通報單，渲染成可列印版面；按「列印／存 PDF」呼叫瀏覽器列印，
// 使用者在列印對話框選「另存為 PDF」即完成輸出（MVP 零外掛，未來可換真匯出模組）。

function formatDate(y: string, m: string, d: string, h: string, min: string): string {
  return `${y} 年 ${m} 月 ${d} 日 ${h} 時 ${min} 分`;
}

// 多選清單 → 頓號串接；空清單顯示破折號；有「其他」補充說明時附註於後。
function formatList(items: readonly string[], note: string): string {
  if (items.length === 0) return '—';
  const base = items.join('、');
  return note.trim() ? `${base}（其他：${note.trim()}）` : base;
}

function formatImpact(form: ReportFormData): string {
  if (form.impact === '有傷害') return `有傷害・${form.injuryLevel ?? ''}`.trim();
  if (form.impact === '無傷害') return '無傷害';
  return '—';
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-[var(--border)] py-2 text-sm last:border-b-0">
      <span className="w-40 shrink-0 text-[var(--text-secondary)]">{label}</span>
      <span className="min-w-0 flex-1 whitespace-pre-wrap text-[var(--text-primary)]">{value || '—'}</span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-5">
      <h2 className="mb-1 text-base font-semibold text-[var(--text-primary)]">{title}</h2>
      <div>{children}</div>
    </section>
  );
}

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

  const f = saved.form;

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
          <p className="mt-1 text-sm text-[var(--text-secondary)]">通報別：{f.reportType ?? '—'}</p>
        </header>

        <Section title="一、個案基本資料">
          <Row label="姓名" value={f.caseName} />
          <Row label="身分證字號" value={f.caseIdNumber} />
          <Row label="性別" value={f.gender ?? '—'} />
          <Row label="生日" value={f.birthday} />
          <Row label="福利身分" value={f.welfare ?? '—'} />
        </Section>

        <Section title="二、事件發生日期">
          <Row
            label="發生時間"
            value={formatDate(f.eventYear, f.eventMonth, f.eventDay, f.eventHour, f.eventMinute)}
          />
        </Section>

        <Section title="三、行政區">
          <Row label="行政區" value={f.district ?? '—'} />
        </Section>

        <Section title="四、事件發生地點">
          <Row
            label="地點"
            value={f.location === '其他' ? `其他：${f.locationNote}` : f.location ?? '—'}
          />
        </Section>

        <Section title="五、對個案的影響程度">
          <Row label="影響程度" value={formatImpact(f)} />
        </Section>

        <Section title="六、關聯單位／人員">
          <Row label="服務提供單位" value={f.serviceUnit} />
          <Row label="服務提供人員" value={formatList(f.servicePersonnel, f.servicePersonnelNote)} />
        </Section>

        <Section title="七、事件內容">
          <Row label="服務過程" value={formatList(f.serviceProcess, f.serviceProcessNote)} />
          <Row label="知悉時即通報" value={formatList(f.immediateNotify, '')} />
        </Section>

        <Section title="八、事發經過說明">
          <Row label="說明" value={f.eventNarrative} />
        </Section>

        <Section title="九、立即處理">
          <Row label="處理方式" value={formatList(f.handling, f.handlingNote)} />
          {f.handling.includes('無介入') && (
            <Row label="無介入細項" value={formatList(f.noIntervention, f.noInterventionNote)} />
          )}
        </Section>

        <Section title="十、通報者資料">
          <Row label="通報者姓名" value={f.reporterName} />
          <Row label="單位" value={f.reporterUnit} />
          <Row label="職稱" value={f.reporterTitle} />
        </Section>

        <Section title="十一、通報日期">
          <Row
            label="通報時間"
            value={formatDate(f.reportYear, f.reportMonth, f.reportDay, f.reportHour, f.reportMinute)}
          />
        </Section>
      </div>
    </div>
  );
}

export default ReportPreview;

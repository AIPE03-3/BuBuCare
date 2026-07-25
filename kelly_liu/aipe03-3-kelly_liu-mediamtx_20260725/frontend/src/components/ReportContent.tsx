import { type ReactNode } from 'react';
import type { ReportFormData } from '../types';

// 通報單內容呈現：把一份 ReportFormData 渲染成十一段唯讀版面。
// ReportPreview（列印／存 PDF）與歷史事件詳情的通報歷程展開皆共用本元件，避免兩處各寫一份而失去同步。

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
    <section className="mt-5 first:mt-0">
      <h2 className="mb-1 text-base font-semibold text-[var(--text-primary)]">{title}</h2>
      <div>{children}</div>
    </section>
  );
}

// 十一段完整通報單內容。header（通報單標題／通報別）由呼叫端各自決定是否顯示。
export function ReportContent({ form }: { form: ReportFormData }) {
  const f = form;

  return (
    <>
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
        <Row label="地點" value={f.location === '其他' ? `其他：${f.locationNote}` : f.location ?? '—'} />
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
    </>
  );
}

export default ReportContent;

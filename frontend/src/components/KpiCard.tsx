type Tone = 'default' | 'danger' | 'warning';

interface KpiCardProps {
  label: string;
  value: string;
  subLabel?: string;
  tone?: Tone;
}

const TONE_CLASS: Record<Tone, string> = {
  default: 'text-[var(--text-primary)]',
  danger: 'text-[var(--danger)]',
  warning: 'text-[var(--warning)]',
};

export function KpiCard({ label, value, subLabel, tone = 'default' }: KpiCardProps) {
  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-4">
      <p className="text-sm text-[var(--text-secondary)]">{label}</p>
      <p className={`mt-2 text-[40px] font-semibold leading-none ${TONE_CLASS[tone]}`}>{value}</p>
      {subLabel && <p className="mt-1 text-xs text-[var(--text-muted)]">{subLabel}</p>}
    </div>
  );
}

export default KpiCard;

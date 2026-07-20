import type { ReactNode } from 'react';

type Tone = 'default' | 'danger' | 'warning';

interface KpiCardProps {
  label: string;
  value: string;
  subLabel?: string;
  tone?: Tone;
  icon?: ReactNode;
}

const TONE_TEXT: Record<Tone, string> = {
  default: 'text-[var(--text-primary)]',
  danger: 'text-[var(--danger)]',
  warning: 'text-[var(--warning)]',
};

const TONE_ICON_BG: Record<Tone, string> = {
  default: 'bg-[var(--brand-soft)] text-[var(--brand)]',
  danger: 'bg-[var(--danger-bg)] text-[var(--danger)]',
  warning: 'bg-[var(--warning-bg)] text-[var(--warning)]',
};

export function KpiCard({ label, value, subLabel, tone = 'default', icon }: KpiCardProps) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface)] p-4 shadow-sm">
      <div className="flex items-center gap-2">
        {icon && (
          <span
            className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${TONE_ICON_BG[tone]}`}
            aria-hidden="true"
          >
            {icon}
          </span>
        )}
        <p className="text-sm text-[var(--text-secondary)]">{label}</p>
      </div>
      <p className={`text-[30px] font-semibold leading-none ${TONE_TEXT[tone]}`}>{value}</p>
      {subLabel && <p className="text-xs text-[var(--text-muted)]">{subLabel}</p>}
    </div>
  );
}

export default KpiCard;

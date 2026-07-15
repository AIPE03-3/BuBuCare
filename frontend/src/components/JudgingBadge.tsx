import { useState } from 'react';
import { ClockIcon } from './icons';

const JUDGING_LOCATIONS = ['西側走廊C', '5F 樓梯間'];

type JudgingBadgeVariant = 'light' | 'dark';

const VARIANT_STYLE: Record<JudgingBadgeVariant, string> = {
  light: 'border border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]',
  dark: 'border border-white/25 bg-white/10 text-white/80',
};

interface JudgingBadgeProps {
  variant?: JudgingBadgeVariant;
}

export function JudgingBadge({ variant = 'light' }: JudgingBadgeProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors duration-150 ${VARIANT_STYLE[variant]}`}
      >
        <ClockIcon aria-hidden="true" className="h-3.5 w-3.5" />
        <span>系統判斷中</span>
        <span className={`font-semibold ${variant === 'dark' ? 'text-white' : 'text-[var(--text-primary)]'}`}>
          {JUDGING_LOCATIONS.length}
        </span>
      </button>

      {open && (
        <div className="absolute right-0 z-10 mt-2 w-44 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-2">
          <ul className="flex flex-col gap-1">
            {JUDGING_LOCATIONS.map((location) => (
              <li key={location} className="px-2 py-1 text-sm text-[var(--text-primary)]">
                {location}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default JudgingBadge;

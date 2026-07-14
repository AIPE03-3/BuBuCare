import { useState } from 'react';

const JUDGING_LOCATIONS = ['西側走廊C', '5F 樓梯間'];

export function JudgingBadge() {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-1 text-xs text-[var(--text-secondary)] transition-colors duration-150"
      >
        <span aria-hidden="true">⏳</span>
        <span>系統判斷中</span>
        <span className="font-semibold text-[var(--text-primary)]">{JUDGING_LOCATIONS.length}</span>
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

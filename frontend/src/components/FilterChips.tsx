import type { EventFilter } from '../types';
import { STATUS_LABEL } from '../types';

const ALL_FILTERS: { value: EventFilter; label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'pending', label: STATUS_LABEL.pending },
  { value: 'in_progress', label: STATUS_LABEL.in_progress },
  { value: 'resolved', label: STATUS_LABEL.resolved },
];

interface FilterChipsProps {
  value: EventFilter;
  onChange: (value: EventFilter) => void;
  options?: EventFilter[];
}

export function FilterChips({ value, onChange, options }: FilterChipsProps) {
  const filters = options ? ALL_FILTERS.filter((f) => options.includes(f.value)) : ALL_FILTERS;
  return (
    <div className="flex flex-wrap gap-2">
      {filters.map((filter) => {
        const active = filter.value === value;
        return (
          <button
            key={filter.value}
            type="button"
            onClick={() => onChange(filter.value)}
            className={`rounded-full border px-3 py-1 text-sm transition-colors duration-150 ${
              active
                ? 'border-[var(--brand)] bg-[var(--brand)] text-white'
                : 'border-[var(--border)] bg-[var(--bg-surface)] text-[var(--text-secondary)]'
            }`}
          >
            {filter.label}
          </button>
        );
      })}
    </div>
  );
}

export default FilterChips;

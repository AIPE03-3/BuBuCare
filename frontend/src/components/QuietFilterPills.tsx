interface QuietFilterPillsProps<T extends string> {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
}

export function QuietFilterPills<T extends string>({ options, value, onChange }: QuietFilterPillsProps<T>) {
  return (
    <div className="flex flex-wrap gap-4">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`text-sm transition-colors duration-150 ${
              active
                ? 'font-medium text-[var(--text-primary)] underline underline-offset-4'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default QuietFilterPills;

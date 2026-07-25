interface QuickToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

export function QuickToggle({ checked, onChange, label }: QuickToggleProps) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--text-secondary)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-4 w-4 accent-[var(--brand)]"
      />
      <span className={checked ? 'font-medium text-[var(--brand)]' : ''}>{label}</span>
    </label>
  );
}

export default QuickToggle;

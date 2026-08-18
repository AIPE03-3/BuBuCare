export function NewEventBanner({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-lg bg-[var(--info)] px-4 py-2 text-left text-sm text-white transition-colors duration-150"
    >
      有 1 筆新事件｜點擊更新
    </button>
  );
}

export default NewEventBanner;

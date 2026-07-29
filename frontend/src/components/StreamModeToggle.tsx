export type StreamMode = 'live' | 'detect';

// 顯示文字集中一份，元件外禁止另外硬編碼。
// 不 export：目前只有本檔在用，而元件檔額外出口常數會讓 React Fast Refresh
// 對整個檔案失效（改一行就整頁重載、狀態清空）。將來真的有別處要用再搬去 types/index.ts。
const STREAM_MODE_LABEL: Record<StreamMode, string> = {
  live: '即時',
  detect: '偵測',
};

const MODES: StreamMode[] = ['live', 'detect'];

interface StreamModeToggleProps {
  value: StreamMode;
  onChange: (mode: StreamMode) => void;
}

/** 「即時／偵測」切換：即時＝原味畫面（cam_in），偵測＝AI 畫框後（cam_out）。 */
export function StreamModeToggle({ value, onChange }: StreamModeToggleProps) {
  return (
    <div role="group" aria-label="畫面來源" className="flex gap-1">
      {MODES.map((mode) => {
        const active = mode === value;
        return (
          <button
            key={mode}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(mode)}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)] ${
              active
                ? 'bg-[var(--brand-soft)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)] hover:bg-[var(--bg-surface-2)]'
            }`}
          >
            {STREAM_MODE_LABEL[mode]}
          </button>
        );
      })}
    </div>
  );
}

export default StreamModeToggle;

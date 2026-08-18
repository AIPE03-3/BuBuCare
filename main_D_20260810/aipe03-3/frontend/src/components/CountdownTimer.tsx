import { formatCountdown } from '../utils/time';

// 接手後 24 小時結案倒數的純顯示元件（未結案列表與事件詳情頁共用）。
// deadline 為該筆事件專屬的到期時間戳，now 由 EventsProvider 每秒 tick 提供，故每筆各自倒數、互不影響。
// 剩不到 1 小時轉危險色提醒；已到期顯示「已逾時」。
const ONE_HOUR_MS = 60 * 60 * 1000;

export function CountdownTimer({ deadline, now }: { deadline: string | null; now: number }) {
  if (!deadline) {
    return <span className="text-[var(--text-muted)]">—</span>;
  }

  const remainMs = new Date(deadline).getTime() - now;
  if (remainMs <= 0) {
    return <span className="font-medium text-[var(--danger)]">已逾時</span>;
  }

  const urgent = remainMs < ONE_HOUR_MS;
  return (
    <span
      className={`tabular-nums ${urgent ? 'font-medium text-[var(--danger)]' : 'text-[var(--text-primary)]'}`}
    >
      {formatCountdown(remainMs)}
    </span>
  );
}

export default CountdownTimer;

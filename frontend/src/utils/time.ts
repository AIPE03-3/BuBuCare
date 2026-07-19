function pad(n: number): string {
  return String(n).padStart(2, '0');
}

export function formatElapsedMinutes(occurredAt: string, now: number): string {
  const diffMs = Math.max(0, now - new Date(occurredAt).getTime());
  if (diffMs < 60000) return '剛剛';
  return `${Math.floor(diffMs / 60000)} 分鐘前`;
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  return `${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
}

// 年月日時分格式：2026/07/15 15:55
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}/${formatDate(iso)} ${formatTime(iso)}`;
}

// 完整年月日（無時分）：2026/07/25。用於續報期限這類「只到日」的到期顯示。
export function formatFullDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getFullYear()}/${formatDate(iso)}`;
}

// 自 fromIso 起加 n 個工作日（排除週六、週日），回傳 ISO。續報期限＝初報日 + 5 個工作日。
export function addBusinessDays(fromIso: string, days: number): string {
  const d = new Date(fromIso);
  let added = 0;
  while (added < days) {
    d.setDate(d.getDate() + 1);
    const weekday = d.getDay(); // 0=週日, 6=週六
    if (weekday !== 0 && weekday !== 6) added += 1;
  }
  return d.toISOString();
}

// 倒數計時：毫秒 → HH:MM:SS（時:分:秒）。負值一律歸零，由呼叫端另行判斷逾時顯示。
export function formatCountdown(ms: number): string {
  const totalSeconds = Math.floor(Math.max(0, ms) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
}

export function formatOfflineDuration(offlineSince: string, now: number): string {
  const diffMs = Math.max(0, now - new Date(offlineSince).getTime());
  const totalMinutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `已離線 ${hours} 小時 ${minutes} 分`;
}

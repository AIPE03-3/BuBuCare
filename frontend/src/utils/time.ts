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

export function formatDateTime(iso: string): string {
  return `${formatDate(iso)} ${formatTime(iso)}`;
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

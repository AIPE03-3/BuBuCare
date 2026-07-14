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

export function formatOfflineDuration(offlineSince: string, now: number): string {
  const diffMs = Math.max(0, now - new Date(offlineSince).getTime());
  const totalMinutes = Math.floor(diffMs / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `已離線 ${hours} 小時 ${minutes} 分`;
}

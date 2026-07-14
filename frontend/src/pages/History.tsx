import { useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { EnvScoreHistory } from './EnvScoreHistory';
import { MediaDownloads } from './MediaDownloads';
import { NotificationHistory } from './NotificationHistory';

type HistoryTab = 'envScore' | 'notifications' | 'videoClips';

const TABS: { value: HistoryTab; label: string }[] = [
  { value: 'envScore', label: '環境安全評分歷史' },
  { value: 'notifications', label: '通報紀錄' },
  { value: 'videoClips', label: '影像片段下載' },
];

export function History() {
  const { role } = useAuth();
  const [tab, setTab] = useState<HistoryTab>('envScore');

  // 通報紀錄 7-3 為 admin 專用；staff 頁籤按鈕本身完全不渲染（非灰階不可點）。
  const visibleTabs = TABS.filter((t) => t.value !== 'notifications' || role === 'admin');

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">歷史紀錄</h1>

      <div className="flex gap-1 border-b border-[var(--border)]">
        {visibleTabs.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            className={`px-4 py-2 text-sm transition-colors duration-150 ${
              tab === t.value
                ? 'border-b-2 border-[var(--brand)] font-medium text-[var(--brand)]'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'videoClips' && <MediaDownloads />}
      {tab === 'notifications' && <NotificationHistory />}
      {tab === 'envScore' && <EnvScoreHistory />}
    </div>
  );
}

export default History;

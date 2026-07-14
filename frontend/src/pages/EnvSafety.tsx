import { useEffect, useState } from 'react';
import { getLatestEnvScores } from '../api/envScores';
import { EnvDangerCard } from '../components/EnvDangerCard';
import { EnvNormalRow } from '../components/EnvNormalRow';
import { EnvOfflineRow } from '../components/EnvOfflineRow';
import { EnvWarningCard } from '../components/EnvWarningCard';
import type { EnvScore } from '../types';
import { groupEnvScores } from '../utils/groupEnvScores';

// 巡檢週期規格為 15 分（見 02_需求規格速查.md），總覽頁「下次更新約 N 分鐘後」依此固定值計算。
const REFRESH_CYCLE_MINUTES = 15;

export function EnvSafety() {
  const [scores, setScores] = useState<EnvScore[]>([]);
  const [loadedAt] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    getLatestEnvScores().then(setScores);
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);

  const groups = groupEnvScores(scores);
  const needsAttentionCount = groups.danger.length + groups.warning.length + groups.offline.length;
  const elapsedMinutes = Math.floor((now - loadedAt) / 60000);
  const nextUpdateMinutes = Math.max(1, REFRESH_CYCLE_MINUTES - (elapsedMinutes % REFRESH_CYCLE_MINUTES));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs text-[var(--text-muted)]">環境安全 › 安全評分總覽</p>
          <h1 className="text-xl font-semibold text-[var(--text-primary)]">安全評分總覽</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)]">
          最後更新於 {elapsedMinutes === 0 ? '剛剛' : `${elapsedMinutes} 分鐘前`}・下次更新約 {nextUpdateMinutes} 分鐘後
        </p>
      </div>

      <div className="flex items-center gap-6">
        <p className="text-sm text-[var(--text-primary)]">
          <span className="font-semibold text-[var(--danger)]">{needsAttentionCount}</span> 台需要注意（
          <span className="text-[var(--danger)]">{groups.danger.length} 危險</span>・
          <span className="text-[var(--warning)]">{groups.warning.length} 警示</span>）
        </p>
        <p className="text-sm text-[var(--text-secondary)]">
          <span className="font-semibold text-[var(--offline)]">{groups.offline.length}</span> 台離線
        </p>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">需要注意（{needsAttentionCount}）</h2>
        <div className="flex flex-col gap-3">
          {groups.danger.map((score) => (
            <EnvDangerCard key={score.score_id} score={score} />
          ))}
          {groups.warning.map((score) => (
            <EnvWarningCard key={score.score_id} score={score} />
          ))}
          {groups.offline.map((score) => (
            <EnvOfflineRow key={score.score_id} score={score} now={now} />
          ))}
          {needsAttentionCount === 0 && (
            <p className="text-sm text-[var(--text-muted)]">目前沒有需要注意的攝影機</p>
          )}
        </div>
      </section>

      <section className="flex flex-col gap-1">
        <h2 className="text-base font-semibold text-[var(--text-primary)]">正常（{groups.normal.length}）</h2>
        <div className="flex flex-col">
          {groups.normal.map((score) => (
            <EnvNormalRow key={score.score_id} score={score} />
          ))}
          {groups.normal.length === 0 && (
            <p className="text-sm text-[var(--text-muted)]">目前沒有狀態正常的攝影機</p>
          )}
        </div>
      </section>
    </div>
  );
}

export default EnvSafety;

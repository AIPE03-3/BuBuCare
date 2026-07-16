import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCameras } from '../api/cameras';
import { DevTestPanel } from '../components/DevTestPanel'; // DEV-TEST：測試按鈕面板，移除測試功能時連同下方使用處一併刪除
import { MonitorIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { CAMERA_LABEL, type Camera } from '../types';

export function Home() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
  const { events } = useEvents();

  useEffect(() => {
    getCameras().then((list) => {
      setCameras(list);
      // 預設帶入第一支鏡頭，讓即時影像一載入就有選定畫面。
      setSelectedCameraId((prev) => prev ?? list[0]?.id ?? null);
    });
  }, []);

  const unresolvedCount = events.filter((e) => e.status !== 'resolved').length;
  const onlineCameraCount = cameras.filter((c) => c.status === 'online').length;
  const selectedCamera = cameras.find((c) => c.id === selectedCameraId) ?? null;

  return (
    <div className="flex flex-col gap-6">
      {/* DEV-TEST：測試按鈕面板（模擬通知／清除測試資料），移除測試功能時刪除此區塊 */}
      <DevTestPanel />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* 左：即時影像區塊（無外框、無標題，頂端貼齊右側卡片；灰色占位框，不接真串流，比照全案影像慣例） */}
        <div className="flex flex-col gap-3">
          <div className="relative flex aspect-video w-full items-center justify-center rounded-xl bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
            {selectedCamera && (
              <span className="absolute left-3 top-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                {selectedCamera.zone}（{selectedCamera.name}）
              </span>
            )}
            {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
          </div>
          <label className="flex flex-col gap-1">
            <span className="sr-only">切換即時影像鏡頭</span>
            <select
              value={selectedCameraId ?? ''}
              onChange={(e) => setSelectedCameraId(Number(e.target.value))}
              className="w-full rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)]"
            >
              {cameras.map((camera) => (
                <option key={camera.id} value={camera.id}>
                  {camera.zone}（{camera.name}）
                </option>
              ))}
            </select>
          </label>
        </div>

        {/* 右：未結案事件 堆疊於 監控中鏡頭 之上 */}
        <div className="flex flex-col gap-6">
          <div className="flex flex-col items-start gap-3 rounded-2xl bg-[var(--brand-dark)] p-6 text-white shadow-sm">
            <div>
              <p className="text-sm text-white/70">未結案事件</p>
              <p className="mt-1 text-[44px] font-semibold leading-none">{unresolvedCount}</p>
            </div>
            <Link
              to="/events"
              className="rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--brand-dark)]"
            >
              前往事件中心
            </Link>
          </div>

          <div className="flex flex-col items-start gap-3 rounded-2xl bg-[var(--info)] p-6 text-white shadow-sm">
            <div>
              <p className="text-sm text-white/70">監控中鏡頭</p>
              <p className="mt-1 text-[44px] font-semibold leading-none">
                {onlineCameraCount}
                <span className="text-lg font-normal text-white/60"> / {cameras.length}</span>
              </p>
            </div>
            <Link
              to="/monitoring"
              className="flex items-center gap-1.5 rounded-lg border border-white/30 px-4 py-2 text-sm text-white transition-colors duration-150 hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--info)]"
            >
              <MonitorIcon className="h-4 w-4" aria-hidden="true" />
              即時監控
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default Home;

import { useEffect, useMemo, useState } from 'react';
import { getCameras, updateCameraName } from '../api/cameras';
import { CameraRow } from '../components/CameraRow';
import { CameraDetailModal } from '../components/CameraDetailModal';
import { ChevronDownIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { groupCamerasByZone } from '../utils/groupCamerasByZone';
import { getDetectingCameraIds } from '../utils/cameraActivity';
import type { Camera } from '../types';

const ALL_ZONES_VALUE = 'all';
const ALL_ZONES_LABEL = '全部區域';

function ColumnHeader({ label, hideOnMobile }: { label: string; hideOnMobile?: boolean }) {
  return (
    <th className={`px-4 py-3 font-medium ${hideOnMobile ? 'hidden sm:table-cell' : ''}`}>
      <span className="inline-flex items-center gap-1">
        {label}
        <ChevronDownIcon className="h-3 w-3" aria-hidden="true" />
      </span>
    </th>
  );
}

export function Monitoring() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [zoneFilter, setZoneFilter] = useState<string>(ALL_ZONES_VALUE);
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
  const { events } = useEvents();

  useEffect(() => {
    getCameras().then(setCameras);
  }, []);

  const zoneGroups = groupCamerasByZone(cameras);
  const detectingIds = getDetectingCameraIds(cameras, events);
  const selectedCamera = cameras.find((c) => c.id === selectedCameraId) ?? null;

  const visibleCameras = useMemo(
    () => (zoneFilter === ALL_ZONES_VALUE ? cameras : cameras.filter((c) => c.zone === zoneFilter)),
    [cameras, zoneFilter],
  );

  function handleUpdateCameraName(id: number, name: string) {
    setCameras((prev) => prev.map((c) => (c.id === id ? { ...c, name } : c)));
    void updateCameraName(id, name);
  }

  return (
    <div className="flex w-full flex-1 flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[var(--text-primary)]">即時監控</h1>

        <div className="flex items-center gap-1">
          <span aria-hidden="true" className="text-xs text-[var(--text-muted)]">▾</span>
          <select
            value={zoneFilter}
            onChange={(e) => setZoneFilter(e.target.value)}
            className="rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-1 text-sm text-[var(--text-primary)]"
          >
            <option value={ALL_ZONES_VALUE}>{ALL_ZONES_LABEL}</option>
            {zoneGroups.map((group) => (
              <option key={group.zone} value={group.zone}>{group.zone}</option>
            ))}
          </select>
        </div>
      </div>

      {visibleCameras.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">目前沒有可顯示的攝影機</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[var(--border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--bg-surface-2)] text-[var(--text-secondary)]">
              <tr>
                <ColumnHeader label="名稱" />
                <ColumnHeader label="區域" hideOnMobile />
                <ColumnHeader label="狀態" />
                <th className="px-4 py-3" aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              {visibleCameras.map((camera) => (
                <CameraRow
                  key={camera.id}
                  camera={camera}
                  isDetecting={detectingIds.has(camera.id)}
                  onSelect={(c) => setSelectedCameraId(c.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selectedCamera && (
        <CameraDetailModal
          camera={selectedCamera}
          isDetecting={detectingIds.has(selectedCamera.id)}
          onClose={() => setSelectedCameraId(null)}
          onNameChange={handleUpdateCameraName}
        />
      )}
    </div>
  );
}

export default Monitoring;

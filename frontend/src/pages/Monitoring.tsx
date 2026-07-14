import { useEffect, useMemo, useState } from 'react';
import { getCameras } from '../api/cameras';
import { CameraCard } from '../components/CameraCard';
import { useEvents } from '../hooks/eventsContext';
import { groupCamerasByZone } from '../utils/groupCamerasByZone';
import { getDetectingCameraIds } from '../utils/cameraActivity';
import type { Camera } from '../types';

const ALL_ZONES_VALUE = 'all';
const ALL_ZONES_LABEL = '全部區域';

export function Monitoring() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [zoneFilter, setZoneFilter] = useState<string>(ALL_ZONES_VALUE);
  const { events } = useEvents();

  useEffect(() => {
    getCameras().then(setCameras);
  }, []);

  const zoneGroups = groupCamerasByZone(cameras);
  const detectingIds = getDetectingCameraIds(cameras, events);

  const visibleZoneGroups = useMemo(
    () => (zoneFilter === ALL_ZONES_VALUE ? zoneGroups : zoneGroups.filter((g) => g.zone === zoneFilter)),
    [zoneGroups, zoneFilter],
  );

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

      {visibleZoneGroups.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">目前沒有可顯示的攝影機</p>
      )}

      {visibleZoneGroups.map((group) => (
        <section key={group.zone} className="flex flex-col gap-2">
          <h2 className="border-b border-[var(--border)] pb-1 text-sm text-[var(--text-secondary)]">
            {group.zone}
          </h2>
          <div className="grid grid-cols-2 gap-4">
            {group.cameras.map((camera) => (
              <CameraCard key={camera.id} camera={camera} isDetecting={detectingIds.has(camera.id)} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export default Monitoring;

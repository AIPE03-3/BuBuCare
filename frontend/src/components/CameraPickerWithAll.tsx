import { useState } from 'react';
import type { Camera } from '../types';
import { groupCamerasByZone } from '../utils/groupCamerasByZone';

// MLOps 每日效能指標（6-1）攝影機選擇器：區域收合清單，
// 多加一個頂部「全部攝影機（全域彙總）」選項（對應 device_id: null）。
// demo 樓層固定 1 樓，沿用 Camera.floor 一律不顯示規則，只呈現「區域・攝影機」。
interface CameraPickerWithAllProps {
  cameras: Camera[];
  selectedId: number | null; // null＝全部攝影機
  onSelect: (id: number | null) => void;
}

export function CameraPickerWithAll({ cameras, selectedId, onSelect }: CameraPickerWithAllProps) {
  const [open, setOpen] = useState(false);
  // 選擇器清單排除已停用（disabled）裝置；離線（offline）仍可查歷史指標故保留。
  const selectable = cameras.filter((c) => c.status !== 'disabled');
  const zones = groupCamerasByZone(selectable);
  const selected = selectedId === null ? null : (cameras.find((c) => c.id === selectedId) ?? null);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-sm font-medium text-[var(--text-primary)] underline underline-offset-4 transition-colors duration-150"
      >
        {selectedId === null ? '全部攝影機（全域彙總）' : selected ? `${selected.zone}・${selected.name}` : '選擇攝影機'}
        <span aria-hidden="true" className="text-xs text-[var(--text-muted)]">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute z-10 mt-2 max-h-80 w-56 overflow-y-auto rounded-lg border border-[var(--border)] bg-[var(--bg-surface)] p-2 shadow-sm">
          <button
            type="button"
            onClick={() => {
              onSelect(null);
              setOpen(false);
            }}
            className={`mb-1 block w-full rounded-md px-2 py-1 text-left text-sm transition-colors duration-150 ${
              selectedId === null
                ? 'font-medium text-[var(--text-primary)] underline underline-offset-4'
                : 'text-[var(--text-secondary)]'
            }`}
          >
            全部攝影機（全域彙總）
          </button>

          {zones.map((group) => (
            <div key={group.zone} className="mb-2 last:mb-0">
              <p className="px-2 py-1 text-xs font-medium text-[var(--text-muted)]">{group.zone}</p>
              {group.cameras.map((camera) => {
                const active = camera.id === selectedId;
                return (
                  <button
                    key={camera.id}
                    type="button"
                    onClick={() => {
                      onSelect(camera.id);
                      setOpen(false);
                    }}
                    className={`block w-full rounded-md px-2 py-1 text-left text-sm transition-colors duration-150 ${
                      active
                        ? 'font-medium text-[var(--text-primary)] underline underline-offset-4'
                        : 'text-[var(--text-secondary)]'
                    }`}
                  >
                    {camera.name}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default CameraPickerWithAll;

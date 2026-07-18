import type { Camera } from '../types';
import { DETECTING_LABEL, OFFLINE_LABEL } from '../types';

interface CameraRowProps {
  camera: Camera;
  isDetecting: boolean;
  onSelect: (camera: Camera) => void;
}

export function CameraRow({ camera, isDetecting, onSelect }: CameraRowProps) {
  // status !== 'online' 一律視為離線視覺（含 disabled 已停用）；本輪不細分 offline/disabled 呈現。
  const offline = camera.status !== 'online';
  const showDetecting = isDetecting && !offline;

  return (
    <tr
      onClick={() => onSelect(camera)}
      className="cursor-pointer border-t border-[var(--border)] bg-[var(--bg-surface)] transition-colors duration-150 hover:bg-[var(--brand-soft)]"
    >
      <td className="px-4 py-3">
        <span className="truncate text-sm font-medium text-[var(--text-primary)]">{camera.name}</span>
      </td>
      <td className="hidden px-4 py-3 text-sm text-[var(--text-secondary)] sm:table-cell">{camera.zone}</td>
      <td className="px-4 py-3">
        {showDetecting ? (
          <span className="inline-flex items-center rounded-full bg-[var(--danger-bg)] px-2 py-0.5 text-xs font-medium text-[var(--danger)]">
            {DETECTING_LABEL}
          </span>
        ) : offline ? (
          <span className="text-xs text-[var(--offline)]">{OFFLINE_LABEL}</span>
        ) : (
          <span className="text-xs text-[var(--text-secondary)]">正常運作</span>
        )}
      </td>
      <td className="px-4 py-3 text-right">
        <span aria-hidden="true" className="text-[var(--text-muted)]">
          ›
        </span>
      </td>
    </tr>
  );
}

export default CameraRow;

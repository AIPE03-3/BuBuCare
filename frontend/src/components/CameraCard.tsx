import type { Camera } from '../types';
import { CAMERA_LABEL, DETECTING_LABEL, OFFLINE_LABEL } from '../types';

interface CameraCardProps {
  camera: Camera;
  isDetecting: boolean;
}

export function CameraCard({ camera, isDetecting }: CameraCardProps) {
  // status !== 'online' 一律視為離線視覺（含 disabled 已停用）；本輪不細分 offline/disabled 呈現。
  const offline = camera.status !== 'online';
  const showDetecting = isDetecting && !offline;

  return (
    // TODO: 下一輪加入單路詳情頁後，點卡片導向對應路由（本輪範圍不做導航）
    <div
      className={`relative flex flex-col gap-2 rounded-xl border bg-[var(--bg-surface)] p-3 transition-colors duration-150 ${
        showDetecting ? 'border-2 border-[var(--danger)]' : 'border-[var(--border)]'
      } ${offline ? 'opacity-50' : ''}`}
    >
      {showDetecting && (
        <span className="absolute left-2 top-2 rounded-full bg-[var(--danger-bg)] px-2 py-0.5 text-xs font-medium text-[var(--danger)]">
          {DETECTING_LABEL}
        </span>
      )}

      {camera.stream_source === null && (
        // stream_source.type 為 'snapshot' 或 'hls' 時，之後在這裡分別接上快照圖／HLS 播放器渲染，本輪僅有 null 情境
        <div className="flex h-28 w-full items-center justify-center rounded-lg bg-[var(--bg-surface-2)] text-center text-xs text-[var(--text-muted)]">
          {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-[var(--text-primary)]">{camera.name}</p>
        {offline && <span className="text-xs text-[var(--offline)]">{OFFLINE_LABEL}</span>}
      </div>
    </div>
  );
}

export default CameraCard;

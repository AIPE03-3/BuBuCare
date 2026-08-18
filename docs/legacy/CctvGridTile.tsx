import type { Camera } from '../types';
import { CAMERA_LABEL, DETECTING_LABEL, OFFLINE_LABEL } from '../types';
import CameraStream from './CameraStream';

interface CctvGridTileProps {
  camera?: Camera;
  tileIndex: number;
  isDetecting?: boolean;
  onSelect?: (camera: Camera) => void;
}

export function CctvGridTile({ camera, tileIndex, isDetecting = false, onSelect }: CctvGridTileProps) {
  // 當為空白填補格時（攝影機總數少於 9 支）
  if (!camera) {
    return (
      <div className="relative flex aspect-video w-full flex-col justify-between overflow-hidden rounded-lg border border-[var(--border)] bg-[#0d1117] p-2 text-xs font-mono text-slate-500 shadow-inner select-none">
        <div className="flex items-center justify-between opacity-60">
          <span className="font-semibold text-slate-400">CAM-{String(tileIndex + 1).padStart(2, '0')}</span>
          <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">NO SIGNAL</span>
        </div>
        <div className="flex flex-col items-center justify-center gap-1 opacity-40">
          <div className="h-6 w-6 rounded-full border border-dashed border-slate-600 flex items-center justify-center text-[10px]">
            OFF
          </div>
          <span className="text-[11px] tracking-widest uppercase">STANDBY</span>
        </div>
        <div className="flex items-center justify-between text-[10px] opacity-40">
          <span>CHANNEL-{tileIndex + 1}</span>
          <span>--:--:--</span>
        </div>
      </div>
    );
  }

  const isOffline = camera.status !== 'online';
  const showDetecting = isDetecting && !isOffline;

  return (
    <div
      onClick={() => onSelect?.(camera)}
      className={`group relative flex aspect-video w-full flex-col justify-between overflow-hidden rounded-lg border transition-all duration-200 cursor-pointer shadow-md bg-slate-950 ${
        showDetecting
          ? 'border-red-500 ring-2 ring-red-500/50 animate-pulse'
          : 'border-slate-800 hover:border-emerald-500 hover:shadow-emerald-900/20'
      }`}
    >
      {/* CCTV 電視牆頂端資訊條 */}
      <div className="absolute top-0 inset-x-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent p-2 text-xs text-white">
        <div className="flex items-center gap-1.5 truncate max-w-[70%]">
          <span className="flex h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
          <span className="font-bold text-slate-100 truncate">{camera.name}</span>
          <span className="text-[10px] text-slate-400">({camera.zone})</span>
        </div>

        <div className="flex items-center gap-1">
          {showDetecting ? (
            <span className="rounded bg-red-600 px-1.5 py-0.5 text-[10px] font-bold text-white tracking-wider animate-bounce">
              {DETECTING_LABEL}
            </span>
          ) : isOffline ? (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
              {OFFLINE_LABEL}
            </span>
          ) : (
            <span className="rounded bg-emerald-950/80 border border-emerald-500/40 px-1.5 py-0.5 text-[10px] text-emerald-400 font-medium">
              LIVE
            </span>
          )}
        </div>
      </div>

      {/* 中央畫面 / 即時 Stream */}
      <div className="relative h-full w-full bg-black flex items-center justify-center">
        {isOffline ? (
          <div className="text-center text-slate-500 text-xs font-mono">
            {CAMERA_LABEL.LIVE_PLACEHOLDER}
          </div>
        ) : (
          <CameraStream cameraLabel={camera.name} />
        )}
      </div>

      {/* CCTV 底端輔助資訊與滿版 Hover 按鈕 */}
      <div className="absolute bottom-0 inset-x-0 z-10 flex items-center justify-between bg-gradient-to-t from-black/80 to-transparent p-2 text-[10px] text-slate-300">
        <span className="font-mono text-slate-400">CAM #{camera.id}</span>

        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onSelect?.(camera);
          }}
          className="opacity-0 group-hover:opacity-100 transition-opacity duration-150 rounded bg-emerald-600 hover:bg-emerald-500 text-white px-2 py-0.5 text-[11px] font-medium shadow"
        >
          滿版監控 🗖
        </button>
      </div>
    </div>
  );
}

export default CctvGridTile;

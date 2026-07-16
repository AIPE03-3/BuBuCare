// ⚠ DEV-TEST 專用元件：測試前端整條流程用。
//   1) 模擬「後端推來一筆跌倒事件」（FullScreenAlert 跳窗 → 接手 → 進入首頁未結案／事件中心即時）。
//   2) 一鍵清除所有測試事件，把前端還原成無資料。
//
// 不需要時的完整移除方式：
//   1. 刪除本檔。
//   2. 移除 Home.tsx 內的 <DevTestPanel /> 與其 import。
//   3. 移除 eventsContext.ts / EventsProvider.tsx 內標註 DEV-TEST 的 injectTestEvent、clearTestEvents。
// 以上三步即可完全還原，不影響真後端 SSE 事件流。

import { getCameras } from '../api/cameras';
import { parseRawEvent, type RawEventPayload } from '../api/events';
import { useEvents } from '../hooks/eventsContext';

// 依所選鏡頭組一筆「後端原始格式」payload，再過真正的 parseRawEvent 轉成 CareEvent，
// 確保測試走的是與真後端完全相同的轉換路徑。
function buildRawPayload(camera: { id: number; name: string; zone: string; floor: string | null }): RawEventPayload {
  return {
    event_id: `evt-test-${Date.now()}`,
    device_id: camera.id,
    device_name: camera.name,
    location: { zone: camera.zone, floor: camera.floor ?? undefined },
    event_type: 'fall',
    status: 'pending',
    verdict: null,
    clip_path: null,
    snapshot_path: null,
    detected_at: new Date().toISOString(),
    notified_at: null,
    staff_id: null,
    company_id: 0,
    yolo_score: 0.94,
    yolo_threshold: 0.8,
    vlm_summary: {
      confidence: 0.94,
      description: '住民疑似跌倒倒地，未見明顯自主起身動作。',
      suggestion: '請立即派員前往確認狀況並協助起身。',
    },
    severity: '高',
  };
}

const devButtonClass =
  'w-fit rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]';

export function DevTestPanel() {
  const { injectTestEvent, clearTestEvents } = useEvents();

  async function handleInject() {
    const cameras = await getCameras();
    // 從即時監控名單取一台鏡頭：優先線上，否則退回第一台。
    const camera = cameras.find((c) => c.status === 'online') ?? cameras[0];
    if (!camera) {
      console.warn('[DevTestPanel] 監控名單無鏡頭可用，無法產生測試事件');
      return;
    }
    injectTestEvent(parseRawEvent(buildRawPayload(camera)));
  }

  return (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={handleInject} className={devButtonClass}>
        測試：模擬後端跌倒通知
      </button>
      <button type="button" onClick={clearTestEvents} className={devButtonClass}>
        清除所有測試資料
      </button>
    </div>
  );
}

export default DevTestPanel;

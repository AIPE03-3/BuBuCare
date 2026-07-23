// ⚠ DEV-TEST 專用元件：測試前端整條流程用。
//   1) 模擬「後端推來一筆跌倒事件」（FullScreenAlert 跳窗 → 接手 → 進入首頁未結案／事件中心即時）。
//   2) 模擬「偵測到危險物品」（潛在危險事件：不跳窗、不寫通報單，僅累積於首頁「潛在危險」卡計數）。
//   3) 一鍵清除所有測試事件，把前端還原成無資料。
//
// 不需要時的完整移除方式：
//   1. 刪除本檔。
//   2. 移除 Home.tsx 內的 <DevTestPanel /> 與其 import。
//   3. 移除 eventsContext.ts / EventsProvider.tsx 內標註 DEV-TEST 的 injectTestEvent、clearTestEvents。
// 以上三步即可完全還原，不影響真後端 SSE 事件流。

import { getCameras } from '../api/cameras';
import { parseRawEvent, type RawEventPayload } from '../api/events';
import { useEvents } from '../hooks/eventsContext';
import { HAZARD_OBJECTS } from '../types';

// 兩種測試事件的 payload 內容（跌倒／物件偵測危險物品）。
const TEST_EVENT_PRESETS = {
  fall: {
    event_type: 'fall',
    description: '住民疑似跌倒倒地，未見明顯自主起身動作。',
    suggestion: '請立即派員前往確認狀況並協助起身。',
  },
  hazard: {
    event_type: 'hazard',
    description: '偵測到危險物品（如利器／熱源）出現在住民活動範圍。',
    suggestion: '請派員確認並移除危險物品，避免住民受傷。',
  },
} as const;

type TestEventKind = keyof typeof TEST_EVENT_PRESETS;

// 依所選鏡頭與事件類型組一筆「後端原始格式」payload，再過真正的 parseRawEvent 轉成 CareEvent，
// 確保測試走的是與真後端完全相同的轉換路徑。
function buildRawPayload(
  camera: { id: number; name: string; zone: string; floor: string | null },
  kind: TestEventKind,
): RawEventPayload {
  const preset = TEST_EVENT_PRESETS[kind];
  return {
    event_id: `evt-test-${Date.now()}`,
    device_id: camera.id,
    device_name: camera.name,
    location: camera.zone,
    event_type: preset.event_type,
    status: 'pending',
    verdict: null,
    clip_path: null,
    snapshot_path: null,
    detected_at: new Date().toISOString(),
    notified_at: null,
    verdict_by: null,
    resolved_by: null,
    company_id: 0,
    yolo_score: 0.94,
    vlm_summary: preset.description,
    // 測試事件是全新事件，尚無通報單
    report_stage: null,
    last_report_at: null,
    // 潛在危險才帶物品類型（demo 隨機挑一種），跌倒事件為 null。
    hazard_object:
      kind === 'hazard' ? HAZARD_OBJECTS[Math.floor(Math.random() * HAZARD_OBJECTS.length)] : null,
  };
}

const devButtonClass =
  'w-fit rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-surface)] px-4 py-2 text-sm text-[var(--text-secondary)] transition-colors duration-150 hover:bg-[var(--brand-soft)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand)]';

export function DevTestPanel() {
  const { injectTestEvent, clearTestEvents } = useEvents();

  async function handleInject(kind: TestEventKind) {
    const cameras = await getCameras();
    // 從即時監控名單取一台鏡頭：優先線上，否則退回第一台。
    const camera = cameras.find((c) => c.status === 'online') ?? cameras[0];
    if (!camera) {
      console.warn('[DevTestPanel] 監控名單無鏡頭可用，無法產生測試事件');
      return;
    }
    injectTestEvent(parseRawEvent(buildRawPayload(camera, kind)));
  }

  return (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => handleInject('fall')} className={devButtonClass}>
        測試：模擬後端跌倒通知
      </button>
      <button type="button" onClick={() => handleInject('hazard')} className={devButtonClass}>
        測試：模擬偵測危險物品
      </button>
      <button type="button" onClick={clearTestEvents} className={devButtonClass}>
        清除所有測試資料
      </button>
    </div>
  );
}

export default DevTestPanel;

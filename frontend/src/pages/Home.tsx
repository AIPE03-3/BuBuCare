import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCameras } from '../api/cameras';
import { DevTestPanel } from '../components/DevTestPanel'; // DEV-TEST：測試按鈕面板，移除測試功能時連同下方使用處一併刪除
import { MonitorIcon } from '../components/icons';
import { useEvents } from '../hooks/eventsContext';
import { formatTime } from '../utils/time';
import { ALERT_LOG_ACTION_LABEL, CAMERA_LABEL, type AlertLogEntry, type Camera } from '../types';

// 切換鏡頭畫面選單。桌機置於右欄頂端、手機緊接鏡頭下方，故抽成元件於兩處各渲染一次
// （以 lg:hidden／hidden lg:block 控制，同一時間僅一個可見，不會重複讀屏）。
function CameraSelect({
  cameras,
  value,
  onChange,
}: {
  cameras: Camera[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <label className="block">
      <span className="sr-only">切換鏡頭畫面選單</span>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full rounded-xl border border-[var(--border)] bg-[var(--bg-surface-2)] px-4 py-3 text-sm font-medium text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
        aria-label="切換鏡頭畫面選單"
      >
        {cameras.length === 0 && <option value="">切換鏡頭畫面選單</option>}
        {cameras.map((camera) => (
          <option key={camera.id} value={camera.id}>
            {camera.zone}（{camera.name}）
          </option>
        ))}
      </select>
    </label>
  );
}

// 徽章配色：接手＝實心綠（--highlight，同未結報事件卡）、潛在危險＝實心紅（--danger，同潛在危險卡示警色）、
// 誤報＝offline 空心外框。兩者皆白字，與首頁卡片的實色底白字用法一致。
const ALERT_LOG_BADGE_CLASS: Record<AlertLogEntry['action'], string> = {
  acknowledged: 'bg-[var(--highlight)] text-white',
  hazard_detected: 'bg-[var(--danger)] text-white',
  false_alarm: 'border border-[var(--offline)] text-[var(--offline)]',
};

// 單筆處理紀錄卡：接手／誤報／潛在危險偵測，三態徽章配色。潛在危險附物品類型。時間顯示到分。
function AlertLogCard({ entry }: { entry: AlertLogEntry }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] px-4 py-3">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${ALERT_LOG_BADGE_CLASS[entry.action]}`}
        >
          {ALERT_LOG_ACTION_LABEL[entry.action]}
        </span>
        <span className="truncate text-sm text-[var(--text-primary)]">
          {entry.cameraName}
          {entry.hazardObject && `・${entry.hazardObject}`}
        </span>
      </div>
      <span className="shrink-0 text-xs text-[var(--text-muted)]">{formatTime(entry.at)}</span>
    </div>
  );
}

export function Home() {
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [selectedCameraId, setSelectedCameraId] = useState<number | null>(null);
  const { events, alertLog, hazardEvents } = useEvents();

  useEffect(() => {
    getCameras().then((list) => {
      setCameras(list);
      // 預設帶入第一支鏡頭，讓即時影像一載入就有選定畫面。
      setSelectedCameraId((prev) => prev ?? list[0]?.id ?? null);
    });
  }, []);

  const unresolvedCount = events.filter((e) => e.status !== 'resolved').length;
  const onlineCameraCount = cameras.filter((c) => c.status === 'online').length;
  const hazardCount = hazardEvents.filter((e) => e.status !== 'resolved').length;
  const selectedCamera = cameras.find((c) => c.id === selectedCameraId) ?? null;

  return (
    <div className="flex flex-col gap-6">
      {/* DEV-TEST：測試按鈕面板（模擬通知／清除測試資料），移除測試功能時刪除此區塊 */}
      <DevTestPanel />

      {/* 主版面：左 2/3（鏡頭＋三張統計卡）／右 1/3（切換選單＋log，隨左欄拉滿高） */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* 左 2/3 */}
        <div className="flex flex-col gap-6 lg:col-span-2">
          {/* 即時影像：灰色占位框（不接真串流，比照全案影像慣例），左上角浮貼所選鏡頭名 */}
          <div className="relative flex aspect-video w-full items-center justify-center rounded-2xl bg-[var(--bg-surface-2)] text-center text-sm text-[var(--text-muted)]">
            {selectedCamera && (
              <span className="absolute left-3 top-3 rounded-md border border-[var(--border)] bg-[var(--bg-surface)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
                {selectedCamera.zone}（{selectedCamera.name}）
              </span>
            )}
            {CAMERA_LABEL.SNAPSHOT_PLACEHOLDER}
          </div>

          {/* 手機：切換選單緊接鏡頭下方（桌機隱藏，改由右欄頂端顯示） */}
          <div className="lg:hidden">
            <CameraSelect cameras={cameras} value={selectedCameraId} onChange={setSelectedCameraId} />
          </div>

          {/* 三張統計卡：未結報事件／監控中鏡頭／潛在危險，並排於鏡頭下方；上下 7:3 分割 */}
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            {/* 未結報事件：全站黑色化改版下唯一保留的品牌綠（--highlight），作為首頁最醒目的 CTA。 */}
            <div className="flex min-h-[210px] flex-col rounded-2xl bg-[var(--highlight)] p-6 text-white shadow-sm">
              <div className="flex flex-[7] flex-col justify-center">
                <p className="text-base text-white/70">未結報事件</p>
                <p className="mt-1 text-6xl font-semibold leading-none">{unresolvedCount}</p>
              </div>
              <div className="flex flex-[3] items-end justify-end">
                <Link
                  to="/events"
                  className="rounded-lg bg-white px-4 py-2 text-sm font-medium text-[var(--highlight)] transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--highlight)]"
                >
                  前往事件中心
                </Link>
              </div>
            </div>

            {/* 監控中鏡頭：純黑底白字（brand-dark） */}
            <div className="flex min-h-[210px] flex-col rounded-2xl bg-[var(--brand-dark)] p-6 text-white shadow-sm">
              <div className="flex flex-[7] flex-col justify-center">
                <p className="text-base text-white/70">監控中鏡頭</p>
                <p className="mt-1 text-6xl font-semibold leading-none">
                  {onlineCameraCount}
                  <span className="text-2xl font-normal text-white/60"> / {cameras.length}</span>
                </p>
              </div>
              <div className="flex flex-[3] items-end justify-end">
                <Link
                  to="/monitoring"
                  className="flex items-center gap-1.5 rounded-lg bg-[var(--brand)] px-4 py-2 text-sm font-medium text-white transition-colors duration-150 hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--brand-dark)]"
                >
                  <MonitorIcon className="h-4 w-4" aria-hidden="true" />
                  即時監控
                </Link>
              </div>
            </div>

            {/* 潛在危險（物件偵測）：不寫通報單、不跳彈窗，僅呈現偵測到的危險物品數量。
                數量為 0 時為淺灰卡（無需注意）；超過 0 時整卡轉紅（--danger）示警。 */}
            <div
              className={`flex min-h-[210px] flex-col rounded-2xl p-6 shadow-sm ${
                hazardCount > 0
                  ? 'bg-[var(--danger)] text-white'
                  : 'border border-[var(--border)] bg-[var(--bg-surface-2)] text-[var(--text-secondary)]'
              }`}
            >
              <div className="flex flex-[7] flex-col justify-center">
                <p className={hazardCount > 0 ? 'text-base text-white/70' : 'text-base text-[var(--text-secondary)]'}>
                  潛在危險
                </p>
                <p
                  className={`mt-1 text-6xl font-semibold leading-none ${
                    hazardCount > 0 ? 'text-white' : 'text-[var(--text-muted)]'
                  }`}
                >
                  {hazardCount}
                </p>
              </div>
              <div className="flex flex-[3] items-end justify-between gap-2">
                <p className={hazardCount > 0 ? 'text-xs text-white/70' : 'text-xs text-[var(--text-muted)]'}>
                  偵測到的危險物品數量
                </p>
                <Link
                  to="/events?tab=hazards"
                  className={`shrink-0 rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                    hazardCount > 0
                      ? 'bg-white text-[var(--danger)] hover:opacity-90 focus-visible:ring-white focus-visible:ring-offset-[var(--danger)]'
                      : 'border border-[var(--text-secondary)] text-[var(--text-secondary)] hover:bg-[var(--brand-soft)] focus-visible:ring-[var(--brand)]'
                  }`}
                >
                  排除危險
                </Link>
              </div>
            </div>
          </div>
        </div>

        {/* 右 1/3：切換鏡頭畫面選單 ＋ 警示處理 log（隨左欄高度拉滿） */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          {/* 桌機：選單在右欄頂端（手機隱藏，已顯示於鏡頭下方） */}
          <div className="hidden lg:block">
            <CameraSelect cameras={cameras} value={selectedCameraId} onChange={setSelectedCameraId} />
          </div>

          {/* log 紀錄：警示被接手／誤報後的處理紀錄清單，最新在前。
              max-h 限制外框高度上限，超出改由內部清單捲動；沒有這個上限，CSS Grid 會讓
              軌道高度隨內容（log 筆數）無限撐高，overflow-y-auto 永遠不會真正生效。 */}
          <div className="flex min-h-[240px] max-h-[65vh] flex-1 flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--bg-surface-2)] p-4">
            <p className="text-sm font-medium text-[var(--text-secondary)]">log 紀錄</p>
            {alertLog.length === 0 ? (
              <div className="flex flex-1 items-center justify-center text-center text-sm text-[var(--text-muted)]">
                尚無處理紀錄
              </div>
            ) : (
              <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
                {alertLog.map((entry) => (
                  <AlertLogCard key={entry.id} entry={entry} />
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

    </div>
  );
}

export default Home;

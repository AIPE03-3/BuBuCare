import { apiClient } from './client';
import type { Camera, DeviceStatus } from '../types';

// 後端 GET /devices 的原始欄位命名，與前端 Camera 不同，須經下方對照轉換。
//
// 串流刻意有兩種形式，兩邊都要用：
//   stream_url*     = 後端組好的 WHEP 網址，瀏覽器拿去連 MediaMTX
//   stream_channel* = 原始頻道名（cam_in…），拿去跟後端換 60 秒串流權杖
// MediaMTX 已開啟身分驗證，只有網址沒有權杖一律 401——所以頻道名不能再丟掉。
interface RawDevice {
  device_id: number;
  device_name: string;
  location: string | null;
  floor: string | null;
  stream_url: string | null;        // 已由後端組好的 WHEP 網址
  stream_url_detect: string | null;
  stream_channel: string | null;    // 換權杖用
  stream_channel_detect: string | null;
  status: 'active' | 'inactive' | 'fault';
}

// 後端字彙 → 前端字彙。inactive＝人為停用、fault＝故障，語意不同不可合併。
const STATUS_MAP: Record<RawDevice['status'], DeviceStatus> = {
  active: 'online',
  inactive: 'disabled',
  fault: 'offline',
};

export async function getCameras(): Promise<Camera[]> {
  const devices = await apiClient.get<RawDevice[]>('/devices');
  return devices.map((d) => ({
    id: d.device_id,
    name: d.device_name,
    zone: d.location ?? '',
    floor: d.floor,
    stream_url: d.stream_url,
    stream_url_detect: d.stream_url_detect,
    stream_channel: d.stream_channel,
    stream_channel_detect: d.stream_channel_detect,
    status: STATUS_MAP[d.status],
  }));
}

// 改名端點 PATCH /devices/{id} 後端已就緒，但本輪範圍不含它，維持前端 mock 行為。
export async function updateCameraName(id: number, name: string): Promise<void> {
  console.info(`updateCameraName 尚未串接後端，camera id：${id}，新名稱：${name}`);
}

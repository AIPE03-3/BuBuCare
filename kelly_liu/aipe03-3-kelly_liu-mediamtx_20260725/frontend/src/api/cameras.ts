import type { Camera } from '../types';
import camerasMock from './mock/cameras.json';

// 後端目前無 /devices 端點（見 04_後端現況與規格落差.md），暫時走 mock，
// 介面維持 async 回傳 Camera[]，之後只需替換函式內部實作即可接上真實 API。
export async function getCameras(): Promise<Camera[]> {
  // JSON 匯入會把 status 推成 string，需斷言回 Camera[]（status 為 DeviceStatus 字面聯合型別）。
  return camerasMock as Camera[];
}

// 後端目前無 /devices 端點（見 04_後端現況與規格落差.md），改名僅在前端 mock 狀態生效；
// 待後端補上更新端點後，這裡改為實際呼叫 API。
export async function updateCameraName(id: number, name: string): Promise<void> {
  console.info(`updateCameraName 尚未串接後端，camera id：${id}，新名稱：${name}`);
}

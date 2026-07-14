import type { Camera } from '../types';

export interface CameraZoneGroup {
  zone: string;
  cameras: Camera[];
}

export function groupCamerasByZone(cameras: Camera[]): CameraZoneGroup[] {
  const order: string[] = [];
  const byZone = new Map<string, Camera[]>();
  for (const camera of cameras) {
    if (!byZone.has(camera.zone)) {
      byZone.set(camera.zone, []);
      order.push(camera.zone);
    }
    byZone.get(camera.zone)!.push(camera);
  }
  return order.map((zone) => ({ zone, cameras: byZone.get(zone)! }));
}

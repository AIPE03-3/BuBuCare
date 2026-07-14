import type { Camera, CareEvent } from '../types';

export function getDetectingCameraIds(cameras: Camera[], events: CareEvent[]): Set<number> {
  const cameraIds = new Set(cameras.map((c) => c.id));
  const detecting = new Set<number>();
  for (const event of events) {
    if (event.status === 'resolved') continue;
    if (!cameraIds.has(event.camera.id)) continue;
    detecting.add(event.camera.id);
  }
  return detecting;
}

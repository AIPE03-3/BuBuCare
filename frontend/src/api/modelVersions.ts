import type { ModelVersion } from '../types';
import { modelVersionsMock } from './mock/modelVersions';

// 模型版本管理（MLOps 6-3~6-6）：後端尚無對應 API，本輪全走 mock，
// 介面維持 async 回傳，之後只需替換函式內部實作即可接上真實 API。
export async function getModelVersions(): Promise<ModelVersion[]> {
  return modelVersionsMock;
}

export async function triggerManualFineTune(): Promise<void> {
  console.info('[triggerManualFineTune] mock，尚未實際串接後端');
}

export async function promoteToProduction(versionId: string): Promise<void> {
  console.info('[promoteToProduction] mock，尚未實際串接後端', versionId);
}

export async function rollbackToVersion(versionId: string): Promise<void> {
  console.info('[rollbackToVersion] mock，尚未實際串接後端', versionId);
}

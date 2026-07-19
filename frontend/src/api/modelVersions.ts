import type { ModelVersion } from '../types';

// 假資料已移除：模型版本清單回傳空陣列，待後端對應 API 就緒後改為實際呼叫。
export async function getModelVersions(): Promise<ModelVersion[]> {
  return [];
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

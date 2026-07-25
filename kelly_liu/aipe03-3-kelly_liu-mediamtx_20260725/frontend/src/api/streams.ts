import { apiClient } from './client';

export interface StreamTokenResponse {
  token: string;
  token_type: 'bearer';
  expires_in: number;
}

export function getStreamToken(cameraPath: string): Promise<StreamTokenResponse> {
  return apiClient.post<StreamTokenResponse>(`/streams/${encodeURIComponent(cameraPath)}/token`);
}

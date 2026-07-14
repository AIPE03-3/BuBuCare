import { useAuth } from './useAuth';

export interface CurrentUser {
  name: string | null;
  employeeCode: string | null;
}

export function useCurrentUser(): CurrentUser {
  const { session } = useAuth();

  return {
    name: session?.display_name ?? null,
    // 待後端補上 /me 端點與員工編號欄位後，於此處改接真實員工編號
    employeeCode: null,
  };
}

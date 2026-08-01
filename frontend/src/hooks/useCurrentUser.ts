import { useAuth } from './useAuth';

export interface CurrentUser {
  name: string | null;
  employeeCode: string | null;
}

export function useCurrentUser(): CurrentUser {
  const { session } = useAuth();

  return {
    name: session?.display_name ?? null,
    // 員編來自登入時解出的 JWT payload.sub（見 api/auth/employeePassword.ts）。
    // ?? null 是為了舊的 localStorage session——它們存的時候還沒有這個欄位。
    employeeCode: session?.employee_code ?? null,
  };
}

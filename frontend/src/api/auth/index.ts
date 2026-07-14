import { AUTH_MODE } from '../../config/app';
import type { AuthProvider } from '../../types';
import { emailOtpProvider } from './emailOtp';
import { employeePasswordProvider } from './employeePassword';

const providers: Record<typeof AUTH_MODE, AuthProvider> = {
  email_otp: emailOtpProvider,
  employee_password: employeePasswordProvider,
};

export const authProvider: AuthProvider = providers[AUTH_MODE];
export { getStoredSession } from './session';

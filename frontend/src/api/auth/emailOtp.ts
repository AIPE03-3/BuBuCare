import type { AuthProvider, AuthSession, Role } from '../../types';
import { setStoredSession, clearStoredSession } from './session';

const OTP_CODE = '123456';

const MOCK_USERS: Record<string, { role: Role; display_name: string }> = {
  'admin@fulilian.demo': { role: 'admin', display_name: '系統管理者' },
  'staff@fulilian.demo': { role: 'staff', display_name: '值班人員' },
};

export const emailOtpProvider: AuthProvider = {
  requestCode(email) {
    return new Promise((resolve, reject) => {
      if (!MOCK_USERS[email]) {
        reject(new Error('查無此帳號'));
        return;
      }
      resolve();
    });
  },

  verifyCode(email, code) {
    return new Promise<AuthSession>((resolve, reject) => {
      const user = MOCK_USERS[email];
      if (!user || code !== OTP_CODE) {
        reject(new Error('驗證碼錯誤或已過期'));
        return;
      }
      const session: AuthSession = {
        token: `mock-token-${email}-${Date.now()}`,
        role: user.role,
        display_name: user.display_name,
      };
      setStoredSession(session);
      resolve(session);
    });
  },

  logout() {
    clearStoredSession();
  },
};

export default emailOtpProvider;

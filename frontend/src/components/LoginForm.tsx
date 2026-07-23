import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, KeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { authProvider } from '../api/auth';
import { AUTH_MODE, FORGOT_PASSWORD_ENABLED } from '../config/app';

const CODE_LENGTH = 6;
const RESEND_COOLDOWN_SECONDS = 60;

type Step = 'email' | 'code';

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : '發生未知錯誤';
}

export function LoginForm() {
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('email');
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [code, setCode] = useState<string[]>(Array(CODE_LENGTH).fill(''));
  const [codeError, setCodeError] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [showForgotModal, setShowForgotModal] = useState(false);

  const codeInputRefs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  async function sendCode() {
    setEmailError(null);
    setCodeError(null);
    setSubmitting(true);
    try {
      await authProvider.requestCode?.(email);
      setInfoMessage('驗證碼已寄出（demo 碼：123456）');
      setCooldown(RESEND_COOLDOWN_SECONDS);
      setStep('code');
    } catch (err) {
      setEmailError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function resendCode() {
    if (cooldown > 0) return;
    setCodeError(null);
    try {
      await authProvider.requestCode?.(email);
      setInfoMessage('驗證碼已寄出（demo 碼：123456）');
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      setCodeError(errorMessage(err));
    }
  }

  async function handleLogin() {
    setCodeError(null);
    setSubmitting(true);
    try {
      await authProvider.verifyCode?.(email, code.join(''));
      navigate('/');
    } catch (err) {
      setCodeError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  function handleBackToEmail() {
    setStep('email');
    setCode(Array(CODE_LENGTH).fill(''));
    setCodeError(null);
    setInfoMessage(null);
    setCooldown(0);
  }

  function handleCodeChange(index: number, e: ChangeEvent<HTMLInputElement>) {
    const digit = e.target.value.replace(/\D/g, '').slice(-1);
    setCode((prev) => {
      const next = [...prev];
      next[index] = digit;
      return next;
    });
    if (digit && index < CODE_LENGTH - 1) {
      codeInputRefs.current[index + 1]?.focus();
    }
  }

  function handleCodeKeyDown(index: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace' && !code[index] && index > 0) {
      codeInputRefs.current[index - 1]?.focus();
    }
  }

  if (AUTH_MODE === 'employee_password') {
    return <PasswordLoginForm />;
  }

  const codeComplete = code.every((digit) => digit !== '');

  return (
    <div className="w-full max-w-[380px] rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 sm:p-8">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">Fulilian 中控台</h1>
      <p className="mt-1 text-sm text-[var(--text-secondary)]">照護監控系統</p>

      {infoMessage && (
        <p className="mt-4 text-xs text-[var(--success)]">{infoMessage}</p>
      )}

      {step === 'email' ? (
        <div className="mt-6">
          <label htmlFor="login-email" className="text-sm text-[var(--text-primary)]">
            Email
          </label>
          <input
            id="login-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition-colors duration-150 focus:border-[var(--brand)]"
            placeholder="you@fulilian.demo"
          />
          {emailError && <p className="mt-1 text-xs text-[var(--danger)]">{emailError}</p>}

          <button
            type="button"
            disabled={!email || submitting}
            onClick={sendCode}
            className="mt-4 w-full rounded-md bg-[var(--brand)] py-2 text-sm font-medium text-white transition-colors duration-150 disabled:opacity-50"
          >
            {submitting ? '傳送中...' : '取得驗證碼'}
          </button>
        </div>
      ) : (
        <div className="mt-6">
          <p className="text-sm text-[var(--text-primary)]">驗證碼</p>
          <div className="mt-1 flex justify-between gap-1 sm:gap-2">
            {code.map((digit, index) => (
              <input
                key={index}
                ref={(el) => {
                  codeInputRefs.current[index] = el;
                }}
                value={digit}
                onChange={(e) => handleCodeChange(index, e)}
                onKeyDown={(e) => handleCodeKeyDown(index, e)}
                inputMode="numeric"
                maxLength={1}
                className="h-11 w-8 rounded-md border border-[var(--border)] text-center text-base text-[var(--text-primary)] outline-none transition-colors duration-150 focus:border-[var(--brand)] sm:w-10"
              />
            ))}
          </div>
          {codeError && <p className="mt-1 text-xs text-[var(--danger)]">{codeError}</p>}

          <button
            type="button"
            disabled={!codeComplete || submitting}
            onClick={handleLogin}
            className="mt-4 w-full rounded-md bg-[var(--brand)] py-2 text-sm font-medium text-white transition-colors duration-150 disabled:opacity-50"
          >
            {submitting ? '登入中...' : '登入'}
          </button>

          <button
            type="button"
            disabled={cooldown > 0}
            onClick={resendCode}
            className="mt-3 w-full text-center text-xs text-[var(--text-secondary)] transition-colors duration-150 disabled:opacity-60"
          >
            {cooldown > 0 ? `重新寄送 (${cooldown}s)` : '重新寄送'}
          </button>

          <button
            type="button"
            onClick={handleBackToEmail}
            className="mt-2 w-full text-center text-sm text-[var(--brand)]"
          >
            ← 更換信箱
          </button>
        </div>
      )}

      {FORGOT_PASSWORD_ENABLED && (
        <div className="mt-6 text-center">
          <button
            type="button"
            onClick={() => setShowForgotModal(true)}
            className="text-sm text-[var(--brand)] hover:underline"
          >
            忘記密碼？
          </button>
        </div>
      )}

      {showForgotModal && (
        <div className="fixed inset-0 flex items-center justify-center bg-[var(--text-primary)]/50 p-4">
          <div className="w-full max-w-[320px] rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 text-center">
            <p className="text-sm text-[var(--text-primary)]">
              密碼協助功能規劃中，請聯絡系統管理員
            </p>
            <button
              type="button"
              onClick={() => setShowForgotModal(false)}
              className="mt-4 rounded-md bg-[var(--brand)] px-4 py-1.5 text-sm text-white"
            >
              關閉
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// 員工帳號＋密碼登入（AUTH_MODE = employee_password）。走 authProvider.loginWithPassword。
function PasswordLoginForm() {
  const navigate = useNavigate();
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    setError(null);
    setSubmitting(true);
    try {
      await authProvider.loginWithPassword?.(account, password);
      navigate('/');
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="w-full max-w-[380px] rounded-xl border border-[var(--border)] bg-[var(--bg-surface)] p-6 sm:p-8">
      <h1 className="text-xl font-semibold text-[var(--text-primary)]">Fulilian 中控台</h1>
      <p className="mt-1 text-sm text-[var(--text-secondary)]">照護監控系統</p>

      <div className="mt-6">
        <label htmlFor="login-account" className="text-sm text-[var(--text-primary)]">
          帳號
        </label>
        <input
          id="login-account"
          type="text"
          autoComplete="username"
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          className="mt-1 w-full rounded-md border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition-colors duration-150 focus:border-[var(--brand)]"
          placeholder="E001"
        />
      </div>

      <div className="mt-4">
        <label htmlFor="login-password" className="text-sm text-[var(--text-primary)]">
          密碼
        </label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && account && password && !submitting) handleSubmit();
          }}
          className="mt-1 w-full rounded-md border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] outline-none transition-colors duration-150 focus:border-[var(--brand)]"
          placeholder="••••••"
        />
      </div>

      {error && <p className="mt-2 text-xs text-[var(--danger)]">{error}</p>}

      <button
        type="button"
        disabled={!account || !password || submitting}
        onClick={handleSubmit}
        className="mt-5 w-full rounded-md bg-[var(--brand)] py-2 text-sm font-medium text-white transition-colors duration-150 disabled:opacity-50"
      >
        {submitting ? '登入中...' : '登入'}
      </button>
    </div>
  );
}

export default LoginForm;

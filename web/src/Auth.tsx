import { useState, type FormEvent } from 'react';
import { Link, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { api, errorText } from './api';
import { Arrow, ErrorNotice, Loading } from './components';
import { useSession } from './session';

export function safeNext(value: string | null) {
  return value?.startsWith('/') &&
    !value.startsWith('//') &&
    !value.includes('\\') &&
    !value.startsWith('/login') &&
    !value.startsWith('/change-password')
    ? value
    : '/';
}
export function Login() {
  const session = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = safeNext(params.get('next'));
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (session.loading) return <Loading />;
  if (session.user)
    return (
      <Navigate
        to={
          session.user.must_change_password
            ? `/change-password?next=${encodeURIComponent(next)}`
            : next
        }
        replace
      />
    );
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const result = await api.login(username.trim(), password);
      session.accept(result);
      navigate(
        result.user.must_change_password
          ? `/change-password?next=${encodeURIComponent(next)}`
          : next,
        { replace: true },
      );
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <p className="eyebrow">继续你的研究</p>
      <h1>登录问砺</h1>
      <p className="subtle">使用管理员为你创建的账号。</p>
      <form onSubmit={submit} className="auth-form">
        <label>
          账号
          <input
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            maxLength={100}
          />
        </label>
        <label>
          密码
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <ErrorNotice message={error} />
        <button className="button primary wide" disabled={busy}>
          {busy ? '正在登录…' : '登录'}
          <Arrow />
        </button>
      </form>
      <p className="form-note">没有账号或忘记密码？请联系管理员。</p>
      <Link className="back-link" to="/">
        <Arrow direction="left" />
        返回提问
      </Link>
    </main>
  );
}

export function PasswordForm({ onDone }: { onDone: () => void }) {
  const session = useSession();
  const [oldPassword, setOldPassword] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    if (password !== confirm) {
      setError('两次输入的新密码不一致。');
      return;
    }
    setBusy(true);
    setError('');
    try {
      session.accept(await api.changePassword(oldPassword, password));
      onDone();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="auth-form" onSubmit={submit}>
      <label>
        当前密码
        <input
          autoFocus
          type="password"
          autoComplete="current-password"
          required
          value={oldPassword}
          onChange={(event) => setOldPassword(event.target.value)}
        />
      </label>
      <label>
        新密码
        <input
          type="password"
          autoComplete="new-password"
          minLength={10}
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        <small>至少 10 个字符，请勿沿用初始密码。</small>
      </label>
      <label>
        再次输入新密码
        <input
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </label>
      <ErrorNotice message={error} />
      <button className="button primary wide" disabled={busy}>
        {busy ? '正在保存…' : '保存新密码'}
      </button>
    </form>
  );
}
export function ChangePassword() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const session = useSession();
  if (!session.user) return <Navigate to="/login" replace />;
  return (
    <main className="auth-page">
      <p className="eyebrow">账户安全</p>
      <h1>{session.user.must_change_password ? '设置你的密码' : '修改密码'}</h1>
      <p className="subtle">
        {session.user.must_change_password
          ? '首次登录，请先替换管理员提供的初始密码。'
          : '新密码保存后立即生效。'}
      </p>
      <PasswordForm onDone={() => navigate(safeNext(params.get('next')), { replace: true })} />
    </main>
  );
}

import { useState, type ReactNode } from 'react';
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { errorText } from './api';
import { ChangePassword, Login, PasswordForm } from './Auth';
import { Brand, Dialog, ErrorNotice, Loading } from './components';
import { History } from './History';
import { Report } from './Report';
import { useSession } from './session';
import { Welcome } from './Welcome';
import { Workbench } from './Workbench';

function RequireUser({ children }: { children: ReactNode }) {
  const session = useSession();
  const location = useLocation();
  if (session.loading) return <Loading />;
  if (session.error && !session.user)
    return (
      <main className="content-shell">
        <ErrorNotice message={session.error} onRetry={() => void session.refresh()} />
      </main>
    );
  if (!session.user)
    return (
      <Navigate
        to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  if (session.user.must_change_password)
    return (
      <Navigate
        to={`/change-password?next=${encodeURIComponent(location.pathname + location.search)}`}
        replace
      />
    );
  return children;
}
export default function App() {
  const session = useSession();
  const location = useLocation();
  const [passwordDialog, setPasswordDialog] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [logoutBusy, setLogoutBusy] = useState(false);
  async function logout() {
    setLogoutBusy(true);
    try {
      await session.logout();
      setError('');
    } catch (error) {
      setError(errorText(error));
    } finally {
      setLogoutBusy(false);
    }
  }
  return (
    <>
      <a className="skip-link" href="#main-content">
        跳转到主要内容
      </a>
      <header className="site-header">
        <Brand />
        <nav aria-label="主要导航">
          {session.user ? (
            <>
              <Link to="/history" className={location.pathname === '/history' ? 'nav-active' : ''}>
                我的研究
              </Link>
              {location.pathname !== '/' && (
                <Link to="/" className="new-research">
                  新建研究<span aria-hidden="true"> +</span>
                </Link>
              )}
              <details className="account-menu">
                <summary>
                  {session.user.username}
                  <span aria-hidden="true">⌄</span>
                </summary>
                <div>
                  <span>{session.user.role === 'admin' ? '管理员账户' : '受邀账户'}</span>
                  <button onClick={() => setPasswordDialog(true)}>修改密码</button>
                  <button disabled={logoutBusy} onClick={() => void logout()}>
                    {logoutBusy ? '正在退出…' : '退出登录'}
                  </button>
                </div>
              </details>
            </>
          ) : (
            <Link className="login-link" to="/login">
              登录 <span aria-hidden="true">↗</span>
            </Link>
          )}
        </nav>
      </header>
      <div id="main-content" tabIndex={-1}>
        <ErrorNotice message={error || session.error} />
        {message && (
          <div className="notice notice-success" role="status">
            {message}
            <button className="text-button" onClick={() => setMessage('')}>
              关闭
            </button>
          </div>
        )}
        <Routes>
          <Route path="/" element={<Welcome />} />
          <Route path="/login" element={<Login />} />
          <Route
            path="/change-password"
            element={session.loading ? <Loading /> : <ChangePassword />}
          />
          <Route
            path="/history"
            element={
              <RequireUser>
                <History />
              </RequireUser>
            }
          />
          <Route
            path="/research/:runId"
            element={
              <RequireUser>
                <Workbench />
              </RequireUser>
            }
          />
          <Route
            path="/research/:runId/report"
            element={
              <RequireUser>
                <Report />
              </RequireUser>
            }
          />
          <Route
            path="*"
            element={
              <main className="auth-page">
                <p className="eyebrow">页面未找到</p>
                <h1>换一个起点</h1>
                <p className="subtle">这个页面不存在，或地址已发生变化。</p>
                <Link className="button primary" to="/">
                  返回首页
                </Link>
              </main>
            }
          />
        </Routes>
      </div>
      <footer className="site-footer">
        <span>
          问砺 <i>·</i> 深度研究智能体
        </span>
        <span>保持好奇，也保持审慎。</span>
      </footer>
      {passwordDialog && (
        <Dialog title="修改密码" onClose={() => setPasswordDialog(false)}>
          <PasswordForm
            onDone={() => {
              setPasswordDialog(false);
              setMessage('密码已更新。');
            }}
          />
        </Dialog>
      )}
    </>
  );
}

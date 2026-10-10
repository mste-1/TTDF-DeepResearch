import { useEffect, useId, useRef, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { statusNames } from './format';
import type { RunStatus } from './types';

export function Arrow({ direction = 'right' }: { direction?: 'right' | 'left' }) {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      style={direction === 'left' ? { transform: 'rotate(180deg)' } : undefined}
    >
      <path d="M4 12h15m-6-6 6 6-6 6" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
export function Brand() {
  return (
    <Link to="/" className="brand" aria-label="问砺 · 深度研究智能体，首页">
      <span className="brand-seal" aria-hidden="true">
        问
      </span>
      <span className="brand-name">问砺</span>
      <span className="brand-desc">深度研究智能体</span>
    </Link>
  );
}
export function Status({ status }: { status: RunStatus }) {
  return (
    <span className={`status status-${status}`}>
      <i />
      {statusNames[status] ?? '状态更新中'}
    </span>
  );
}
export function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return message ? (
    <div className="notice notice-error" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button className="text-button" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  ) : null;
}
export function Loading({ label = '正在加载…' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="loading-dot" />
      {label}
    </div>
  );
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-mark" aria-hidden="true">
        —
      </span>
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  );
}
export function Dialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={id}
      className="dialog"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog-inner">
        <button className="close-button" aria-label="关闭" onClick={onClose}>
          ×
        </button>
        <h2 id={id}>{title}</h2>
        {children}
      </div>
    </dialog>
  );
}

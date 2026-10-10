import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, errorText } from './api';
import { Arrow, Empty, ErrorNotice, Loading, Status } from './components';
import { dateTime, isTerminal, hasReport } from './format';
import { RunActions } from './RunActions';
import { useSession } from './session';
import type { ResearchRun } from './types';

export function History() {
  const { user } = useSession();
  const [scope, setScope] = useState('mine');
  const [filter, setFilter] = useState('');
  const [items, setItems] = useState<ResearchRun[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [moreBusy, setMoreBusy] = useState(false);
  const paged = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    let disposed = false;
    let busy = false;
    const controller = new AbortController();
    generation.current += 1;
    paged.current = false;
    setLoading(true);
    setItems([]);
    setCursor(null);
    async function load() {
      if (busy) return;
      busy = true;
      try {
        const result = await api.list(
          new URLSearchParams({ scope, ...(filter ? { status: filter } : {}) }).toString(),
          controller.signal,
        );
        if (!disposed) {
          setItems((previous) =>
            paged.current
              ? [
                  ...result.items,
                  ...previous.filter((item) => !result.items.some((fresh) => fresh.id === item.id)),
                ]
              : result.items,
          );
          if (!paged.current) setCursor(result.next_cursor ?? null);
          setError('');
        }
      } catch (error) {
        if (!disposed) setError(errorText(error));
      } finally {
        busy = false;
        if (!disposed) setLoading(false);
      }
    }
    void load();
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') void load();
    }, 10000);
    return () => {
      disposed = true;
      controller.abort();
      clearInterval(timer);
    };
  }, [scope, filter, revision]);
  async function more() {
    if (!cursor || moreBusy) return;
    const currentGeneration = generation.current;
    setMoreBusy(true);
    try {
      const result = await api.list(
        new URLSearchParams({ scope, ...(filter ? { status: filter } : {}), cursor }).toString(),
      );
      if (currentGeneration !== generation.current) return;
      paged.current = true;
      setItems((previous) => [
        ...previous,
        ...result.items.filter((item) => !previous.some((old) => old.id === item.id)),
      ]);
      setCursor(result.next_cursor ?? null);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setMoreBusy(false);
    }
  }
  return (
    <main className="history-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">你的研究书架</p>
          <h1>{scope === 'all' ? '全部研究' : '我的研究'}</h1>
          <p className="subtle">每个问题，都有一份独立的研究记录。</p>
        </div>
        <Link className="button primary" to="/">
          新建研究
          <Arrow />
        </Link>
      </div>
      <div className="list-toolbar">
        <div className="segmented" aria-label="筛选研究状态">
          {[
            ['', '全部'],
            ['running', '运行中'],
            ['queued', '排队中'],
            ['ended', '已结束'],
          ].map(([value, label]) => (
            <button
              key={value}
              className={filter === value ? 'active' : ''}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {user?.role === 'admin' && (
          <label className="scope-select">
            查看范围
            <select value={scope} onChange={(event) => setScope(event.target.value)}>
              <option value="mine">我的研究</option>
              <option value="all">全部研究</option>
            </select>
          </label>
        )}
      </div>
      <ErrorNotice message={error} onRetry={() => setRevision(revision + 1)} />
      {loading ? (
        <Loading />
      ) : !items.length && !error ? (
        <Empty title="这里还没有研究记录">
          {filter ? '试试其他筛选条件。' : '从一个你关心的问题开始。'}
        </Empty>
      ) : (
        <div className="research-list">
          {items.map((run) => (
            <article className="research-row" key={run.id}>
              <div className="research-row-main">
                <div className="row-meta">
                  <Status status={run.status} />
                  <time>{dateTime(run.created_at)}</time>
                  {scope === 'all' && <span>{run.username ?? '用户'}</span>}
                </div>
                <Link
                  className="research-title"
                  to={`/research/${run.id}${hasReport(run.status) ? '/report' : ''}`}
                >
                  {run.topic}
                </Link>
                <p className="row-note">
                  {run.status === 'queued'
                    ? `等待执行${run.queue_position ? ` · 队列第 ${run.queue_position} 位` : ''}`
                    : run.status === 'cancelling'
                      ? '正在保存已收到的成果并停止执行'
                      : isTerminal(run.status) && !hasReport(run.status)
                        ? '可查看已保存的阶段成果'
                        : run.has_warnings
                          ? '存在研究警告，可在过程详情查看'
                          : hasReport(run.status)
                            ? '报告已保存'
                            : '研究过程与阶段成果持续更新'}
                </p>
              </div>
              <div className="row-controls">
                <Link className="text-button" to={`/research/${run.id}`}>
                  查看过程 <span aria-hidden="true">↗</span>
                </Link>
                <RunActions run={run} allowDelete onChange={() => setRevision(revision + 1)} />
              </div>
            </article>
          ))}
        </div>
      )}
      {cursor && (
        <button className="button load-more" disabled={moreBusy} onClick={() => void more()}>
          {moreBusy ? '正在加载…' : '加载更早的研究'}
        </button>
      )}
    </main>
  );
}

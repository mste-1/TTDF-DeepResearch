import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, clearSubmission, errorText, submissionKey } from './api';
import { Arrow, ErrorNotice, Status } from './components';
import { dateTime, hasReport } from './format';
import { useSession } from './session';
import type { ResearchRun } from './types';

const DRAFT_KEY = 'wenli.question';
export function readDraft(): { topic: string; instructions: string } {
  try {
    const saved = JSON.parse(sessionStorage.getItem(DRAFT_KEY) ?? '{}');
    return {
      topic: typeof saved.topic === 'string' ? saved.topic : '',
      instructions: typeof saved.instructions === 'string' ? saved.instructions : '',
    };
  } catch {
    return { topic: '', instructions: '' };
  }
}
export function Welcome() {
  const session = useSession();
  const navigate = useNavigate();
  const [draft, setDraft] = useState(readDraft);
  const [expanded, setExpanded] = useState(Boolean(draft.instructions));
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState('');
  const [recent, setRecent] = useState<ResearchRun[]>([]);
  const [recentError, setRecentError] = useState('');
  useEffect(() => {
    try {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
      /* Input remains available in the current page. */
    }
  }, [draft]);
  useEffect(() => {
    if (!session.user || session.user.must_change_password) {
      setRecent([]);
      return;
    }
    const abort = new AbortController();
    api
      .list('scope=mine&limit=3', abort.signal)
      .then((result) => {
        setRecent(result.items.slice(0, 3));
        setRecentError('');
      })
      .catch((error) => {
        if (!abort.signal.aborted) setRecentError(errorText(error));
      });
    return () => abort.abort();
  }, [session.user]);
  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (inFlight.current || !draft.topic.trim()) return;
    if (!session.user) {
      navigate('/login?next=%2F');
      return;
    }
    if (session.user.must_change_password) {
      navigate('/change-password?next=%2F');
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError('');
    const input = { topic: draft.topic.trim(), instructions: draft.instructions.trim() };
    try {
      const run = await api.create(input, submissionKey(input));
      clearSubmission();
      setDraft({ topic: '', instructions: '' });
      try {
        sessionStorage.removeItem(DRAFT_KEY);
      } catch {
        /* Optional local state. */
      }
      navigate(`/research/${run.id}`);
    } catch (error) {
      setError(errorText(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <main className="welcome">
      <div className="welcome-intro">
        <p className="eyebrow">
          <span />
          始于一问，砺于深研
        </p>
        <h1>
          你想把什么问题
          <br className="small-break" />
          研究透<span className="cinnabar">？</span>
        </h1>
        <p>从一个问题出发，形成有依据的调研报告。</p>
      </div>
      <form className="question-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="topic">
          研究主题
        </label>
        <textarea
          id="topic"
          value={draft.topic}
          onChange={(event) => setDraft({ ...draft, topic: event.target.value })}
          placeholder="输入想研究的主题或具体问题……"
          maxLength={2000}
          required
          rows={4}
          onKeyDown={(event) => {
            if (
              event.key === 'Enter' &&
              (event.ctrlKey || event.metaKey) &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <div className="question-tools">
          <button
            type="button"
            className="text-button expand-input"
            onClick={() => setExpanded(!expanded)}
            aria-expanded={expanded}
          >
            <span aria-hidden="true">{expanded ? '−' : '+'}</span> 补充研究目的或范围
          </button>
          <button
            type="submit"
            className="button primary"
            disabled={busy || session.loading || !draft.topic.trim()}
          >
            {busy ? '正在提交…' : '开始研究'}
            <Arrow />
          </button>
        </div>
        {expanded && (
          <div className="optional-input">
            <label htmlFor="instructions">
              补充说明 <span>选填</span>
            </label>
            <textarea
              id="instructions"
              rows={3}
              maxLength={5000}
              placeholder="例如：关注中国市场；面向产品经理；比较最近三年的变化。"
              value={draft.instructions}
              onChange={(event) => setDraft({ ...draft, instructions: event.target.value })}
            />
          </div>
        )}
      </form>
      <ErrorNotice message={error} />
      <div className="topic-examples">
        <span>试试</span>
        {['技术路线比较', '行业发展研究', '产品决策分析'].map((topic) => (
          <button key={topic} onClick={() => setDraft({ ...draft, topic })}>
            {topic}
            <span aria-hidden="true">↗</span>
          </button>
        ))}
      </div>
      <p className="welcome-footnote">简报与初稿 · 多方向研究 · 质疑与修订 · 完整报告</p>
      {session.user && (
        <section className="recent-research">
          <div className="section-heading">
            <h2>最近研究</h2>
            <Link to="/history">
              查看全部 <span aria-hidden="true">↗</span>
            </Link>
          </div>
          <ErrorNotice message={recentError} />
          {recent.map((run) => (
            <Link
              className="recent-row"
              key={run.id}
              to={`/research/${run.id}${hasReport(run.status) ? '/report' : ''}`}
            >
              <span>{run.topic}</span>
              <Status status={run.status} />
              <time>{dateTime(run.created_at)}</time>
            </Link>
          ))}
          {!recent.length && !recentError && (
            <p className="subtle">你的第一项研究，从上面的问题开始。</p>
          )}
        </section>
      )}
    </main>
  );
}

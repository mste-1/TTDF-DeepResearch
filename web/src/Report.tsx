import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from './api';
import { Arrow, Empty, ErrorNotice, Loading, Status } from './components';
import { dateTime, hasReport } from './format';
import { Markdown, markdownHeadings } from './Markdown';
import { useRun } from './useRun';
import { useArtifact } from './useArtifact';

export function ReportContents({ headings }: { headings: ReturnType<typeof markdownHeadings> }) {
  const [open, setOpen] = useState(() => window.matchMedia?.('(min-width: 761px)').matches ?? true);
  useEffect(() => {
    const media = window.matchMedia?.('(min-width: 761px)');
    if (!media) return;
    const change = (event: MediaQueryListEvent) => setOpen(event.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  return (
    <aside className="report-toc">
      <details open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
        <summary>章节目录</summary>
        <nav aria-label="报告章节目录">
          {headings.map((heading) => (
            <a key={heading.id} href={`#${heading.id}`} className={`toc-level-${heading.level}`}>
              {heading.text}
            </a>
          ))}
          {!headings.length && <span className="subtle">此报告未设置章节标题。</span>}
        </nav>
      </details>
    </aside>
  );
}

export function Report() {
  const { runId = '' } = useParams();
  const { run, error, refresh } = useRun(runId);
  const artifact =
    run?.id === runId && hasReport(run.status)
      ? [...(run.artifacts ?? [])]
          .reverse()
          .find((item) => ['final_report', 'final', 'report'].includes(item.kind) && !item.partial)
      : undefined;
  const resource = useArtifact(runId, artifact);
  if (!run)
    return (
      <main className="content-shell">
        <ErrorNotice message={error} onRetry={refresh} />
        {!error && <Loading />}
      </main>
    );
  const headings = markdownHeadings(resource.body?.markdown ?? '');
  return (
    <main className="report-page">
      <div className="report-tools">
        <Link className="back-link" to={`/research/${run.id}`}>
          <Arrow direction="left" />
          返回研究过程
        </Link>
        {artifact && hasReport(run.status) && (
          <a className="button" href={api.reportUrl(run.id)} download>
            下载 Markdown ↓
          </a>
        )}
      </div>
      <header className="report-heading">
        <p className="eyebrow">问砺研究报告</p>
        <h1>{run.topic}</h1>
        <div className="run-meta">
          <Status status={run.status} />
          <time>{dateTime(run.finished_at ?? run.created_at)}</time>
        </div>
      </header>
      <ErrorNotice message={error} onRetry={refresh} />
      {run.has_warnings && (
        <div className="notice notice-warning">
          本报告包含研究警告。<Link to={`/research/${run.id}`}>查看研究过程与警告说明</Link>
        </div>
      )}
      {artifact && hasReport(run.status) ? (
        <div className="report-layout">
          <ReportContents headings={headings} />
          <article className="report-paper">
            {resource.loading && <Loading label="正在加载报告正文…" />}
            <ErrorNotice message={resource.error} onRetry={resource.retry} />
            {resource.body && <Markdown content={resource.body.markdown} />}
            {resource.body && (
              <div className="report-end">
                <span />
                问砺 · 以研究回应问题
                <span />
              </div>
            )}
          </article>
        </div>
      ) : (
        <Empty title="完整报告尚不可用">
          <Link to={`/research/${run.id}`}>返回研究过程，查看已保存的阶段成果</Link>
        </Empty>
      )}
    </main>
  );
}

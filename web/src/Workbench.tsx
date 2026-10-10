import { lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from './api';
import { Arrow, Dialog, Empty, ErrorNotice, Loading, Status } from './components';
import {
  dateTime,
  elapsed,
  eventMessage,
  failureMessage,
  hasReport,
  isTerminal,
  nodeStatus,
  safeExternalUrl,
  stageName,
} from './format';
import { Markdown } from './Markdown';
import { RunActions } from './RunActions';
import { useSession } from './session';
import type { Artifact, ResearchRun, RunEvent, StageNode } from './types';
import { useRun } from './useRun';
import { useArtifact } from './useArtifact';
const Graph = lazy(() => import('./Graph'));

function ArtifactView({
  artifact,
  runId,
  onClose,
  resource,
}: {
  artifact: Artifact;
  runId: string;
  onClose: () => void;
  resource: ReturnType<typeof useArtifact>;
}) {
  return (
    <Dialog title={artifact.title || stageName(artifact.kind)} onClose={onClose}>
      <div className="artifact-meta">
        <span>{artifact.partial ? '未完成 · 已保存内容' : '阶段成果'}</span>
        <time>{dateTime(artifact.created_at)}</time>
        <a className="text-button" href={api.artifactUrl(runId, artifact.id)} download>
          下载 Markdown ↓
        </a>
      </div>
      {artifact.kind === 'draft' && (
        <p className="notice">初始草稿 · 待核验。此稿在外部资料研究前生成，请结合后续成果阅读。</p>
      )}
      {artifact.kind === 'evaluation' && (
        <p className="notice">评分由模型给出，供研究过程参考，不代表事实准确率。</p>
      )}
      {resource.loading && <Loading label="正在加载成果正文…" />}
      <ErrorNotice message={resource.error} onRetry={resource.retry} />
      {resource.body && <Markdown content={resource.body.markdown} />}
    </Dialog>
  );
}
function Artifacts({
  artifacts,
  onOpen,
}: {
  artifacts: Artifact[];
  onOpen: (artifact: Artifact) => void;
}) {
  return (
    <div className="artifact-list">
      {artifacts.map((artifact) => (
        <button className="artifact-button" key={artifact.id} onClick={() => onOpen(artifact)}>
          <span className="document-icon" aria-hidden="true">
            ≡
          </span>
          <span>
            <strong>{artifact.title || stageName(artifact.kind)}</strong>
            <small>
              {artifact.partial ? '未完成' : `版本 ${artifact.version || 1}`} ·{' '}
              {dateTime(artifact.created_at)}
            </small>
          </span>
          <span aria-hidden="true">↗</span>
        </button>
      ))}
    </div>
  );
}
export function Inspector({
  run,
  node,
  events,
  historyError,
  historyLoading,
  hasEarlier,
  loadEarlier,
  onOpen,
}: {
  run: ResearchRun;
  node?: StageNode;
  events: RunEvent[];
  historyError: string;
  historyLoading: boolean;
  hasEarlier: boolean;
  loadEarlier: () => void;
  onOpen: (artifact: Artifact) => void;
}) {
  const [tab, setTab] = useState('artifacts');
  const artifacts = (run.artifacts ?? []).filter(
    (artifact) => !node || artifact.agent_instance_id === node.id,
  );
  const sources = (run.sources ?? []).filter(
    (source) => !node || source.agent_instance_id === node.id,
  );
  const activity = events.filter(
    (event) =>
      !node || event.agent_instance_id === node.id || event.data?.agent_instance_id === node.id,
  );
  return (
    <aside className="inspector" aria-label="研究详情">
      <div className="inspector-heading">
        <p className="eyebrow">{node ? stageName(node.stage) : '研究全览'}</p>
        <h2>{node?.label || '研究成果与资料'}</h2>
        <p className="subtle">
          {node
            ? nodeStatus(node.status)
            : `${run.artifacts?.length ?? 0} 份成果 · ${run.sources?.length ?? 0} 个资料来源`}
        </p>
      </div>
      <div className="inspector-tabs" role="tablist" aria-label="研究详情分类">
        {[
          ['artifacts', '成果'],
          ['sources', '来源'],
          ['activity', '活动'],
        ].map(([value, label]) => (
          <button
            key={value}
            id={`tab-${value}`}
            role="tab"
            aria-selected={tab === value}
            aria-controls="inspector-panel"
            onClick={() => setTab(value)}
          >
            {label}
            {value === 'sources' && sources.length > 0 && <span>{sources.length}</span>}
          </button>
        ))}
      </div>
      <div
        className="inspector-content"
        id="inspector-panel"
        role="tabpanel"
        aria-labelledby={`tab-${tab}`}
      >
        {tab === 'artifacts' &&
          (artifacts.length ? (
            <Artifacts artifacts={artifacts} onOpen={onOpen} />
          ) : (
            <Empty title="成果正在形成">
              {node ? '此节点的成果保存后会显示在这里。' : '研究开始后，这里会逐步收录阶段成果。'}
            </Empty>
          ))}
        {tab === 'sources' &&
          (sources.length ? (
            <ol className="sources-list">
              {sources.map((source, index) => (
                <li key={`${source.url}-${index}`}>
                  <span className="source-number">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    {safeExternalUrl(source.url) ? (
                      <a
                        href={safeExternalUrl(source.url)}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {source.title || source.url}
                        <span aria-hidden="true"> ↗</span>
                      </a>
                    ) : (
                      <span>{source.title || '参考资料'}</span>
                    )}
                    <small>
                      {safeExternalUrl(source.url) ? new URL(source.url).hostname : '链接不可用'}
                    </small>
                    {source.query && <p>{source.query}</p>}
                  </div>
                </li>
              ))}
            </ol>
          ) : (
            <Empty title="暂无资料来源">检索到的资料会随研究持续补充。</Empty>
          ))}
        {tab === 'activity' && (
          <>
            <ErrorNotice message={historyError} onRetry={loadEarlier} />
            {!run.history_available && (
              <p className="notice">详细过程记录已过期，已保存的图与成果仍可阅读。</p>
            )}
            {activity.length ? (
              <ol className="activity-list">
                {activity
                  .slice()
                  .reverse()
                  .map((event) => {
                    const message = eventMessage(event);
                    return (
                      <li key={event.seq}>
                        <i />
                        <div>
                          <p>{message || '研究进展已更新'}</p>
                          <time>{dateTime(event.timestamp || event.created_at)}</time>
                        </div>
                      </li>
                    );
                  })}
              </ol>
            ) : historyLoading ? (
              <Loading label="正在加载活动…" />
            ) : (
              !historyError && (
                <Empty title={hasEarlier ? '此节点暂无已载入活动' : '暂无活动记录'}>
                  {hasEarlier
                    ? '可加载更早记录，查看先前的研究阶段。'
                    : '已保存的研究进展会记录在这里。'}
                </Empty>
              )
            )}
            {run.history_available && hasEarlier && (
              <button className="button load-more" disabled={historyLoading} onClick={loadEarlier}>
                {historyLoading ? '正在加载更早活动…' : '加载更早活动'}
              </button>
            )}
          </>
        )}
      </div>
    </aside>
  );
}

export function Workbench() {
  const { runId = '' } = useParams();
  const {
    run,
    error,
    connection,
    events,
    historyError,
    historyLoading,
    hasEarlier,
    loadEarlier,
    refresh,
  } = useRun(runId);
  const session = useSession();
  const [selected, setSelected] = useState<string>();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [showGraph, setShowGraph] = useState(false);
  const [allRounds, setAllRounds] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => {
    setSelected(undefined);
    setArtifact(null);
    setAllRounds(false);
  }, [runId]);
  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, []);
  const stages = run?.snapshot?.nodes ?? [];
  const currentArtifact =
    run?.id === runId ? (run.artifacts?.find((item) => item.id === artifact?.id) ?? null) : null;
  const artifactResource = useArtifact(runId, currentArtifact);
  const maxIteration = Math.max(0, ...stages.map((node) => node.iteration ?? 0));
  const visibleStages = useMemo(
    () =>
      allRounds
        ? stages
        : stages.filter(
            (stage) =>
              !stage.iteration || stage.iteration === maxIteration || stage.status === 'running',
          ),
    [stages, allRounds, maxIteration],
  );
  if (!run)
    return (
      <main className="content-shell">
        <ErrorNotice message={error} onRetry={refresh} />
        {!error && <Loading label="正在打开研究书案…" />}
        {error && (
          <Link to="/login" className="text-button">
            会话过期时，可重新登录
          </Link>
        )}
      </main>
    );
  const node = stages.find((stage) => stage.id === selected);
  const ended = isTerminal(run.status);
  const activeStage = [...stages].reverse().find((stage) => stage.status === 'running');
  return (
    <main className="workbench">
      <div className="workbench-heading">
        <div>
          <Link className="back-link" to="/history">
            <Arrow direction="left" />
            我的研究
          </Link>
          <h1>{run.topic}</h1>
          <div className="run-meta">
            <Status status={run.status} />
            <span>
              {run.started_at
                ? `已耗时 ${elapsed(run.started_at, run.finished_at)}`
                : run.queue_position
                  ? `队列第 ${run.queue_position} 位`
                  : '等待执行'}
            </span>
            {session.user?.id !== run.user_id && (
              <span>所属账号：{run.username ?? '其他用户'} · 只读</span>
            )}
          </div>
        </div>
        <RunActions run={run} onChange={refresh} />
      </div>
      <ErrorNotice message={error} onRetry={refresh} />
      {run.status === 'queued' && (
        <div className="notice">
          {run.queue_position
            ? `当前位于等待队列第 ${run.queue_position} 位。`
            : '正在等待可用的研究位置。'}
          你可以关闭页面，研究会在轮到时自动开始。
        </div>
      )}
      {run.status === 'cancelling' && (
        <div className="notice">正在保存已收到的成果并停止执行，请稍候。</div>
      )}
      {ended && !hasReport(run.status) && (
        <div className="notice">
          {run.error_message ||
            run.status_message ||
            failureMessage(run.failure_code) ||
            '本次研究已结束，已保存的阶段成果仍可查看和下载。'}
          重新生成会创建新任务，从头开始。
        </div>
      )}
      {run.has_warnings && (
        <div className="notice notice-warning">
          本次研究存在警告，请结合资料判断报告内容。
          {run.warnings?.map((warning, index) => (
            <p key={index}>{warning.message}</p>
          ))}
        </div>
      )}
      <div className="process-strip">
        <div className="process-spine">
          <span>简报</span>
          <span>→</span>
          <span>初稿</span>
          <span>→</span>
          <span className={activeStage ? 'current' : ''}>研究与修订</span>
          <span>→</span>
          <span className={hasReport(run.status) ? 'current' : ''}>最终报告</span>
        </div>
        <span className={`connection connection-${connection}`}>
          <i />
          {connection === 'live'
            ? '实时同步'
            : connection === 'closed'
              ? '成果已保存'
              : connection === 'connecting'
                ? '正在连接'
                : '连接恢复中 · 自动刷新'}
        </span>
      </div>
      <div className="workbench-body">
        <section
          className={`graph-area ${showGraph ? 'mobile-show-graph' : ''}`}
          aria-label="研究过程"
        >
          <div className="graph-toolbar">
            <span>
              {activeStage
                ? `当前：${stageName(activeStage.stage)}`
                : ended
                  ? '研究过程'
                  : '等待研究开始'}
            </span>
            <div>
              {maxIteration > 1 && (
                <button className="text-button" onClick={() => setAllRounds(!allRounds)}>
                  {allRounds ? '收起历史轮次' : `展开历史轮次（${maxIteration}）`}
                </button>
              )}
              <button className="text-button" onClick={() => setSelected(undefined)}>
                全部成果
              </button>
            </div>
          </div>
          {visibleStages.length ? (
            <Suspense fallback={<Loading label="正在加载协作图…" />}>
              <Graph
                stages={visibleStages}
                edges={run.snapshot.edges ?? []}
                sources={run.sources ?? []}
                selected={selected}
                onSelect={setSelected}
              />
            </Suspense>
          ) : (
            <div className="graph-waiting">
              <span className="paper-outline" aria-hidden="true">
                问
              </span>
              <h2>研究从这里展开</h2>
              <p>简报、研究与修订会逐步呈现在这张书案上。</p>
            </div>
          )}
        </section>
        <section className={`mobile-stages ${showGraph ? 'is-hidden' : ''}`} aria-label="研究阶段">
          <div className="section-heading">
            <h2>研究过程</h2>
            <button className="text-button" onClick={() => setShowGraph(true)}>
              查看关系图
            </button>
          </div>
          {visibleStages.length ? (
            visibleStages.map((stage) => (
              <button
                key={stage.id}
                className={`mobile-stage ${selected === stage.id ? 'selected' : ''}`}
                onClick={() => setSelected(stage.id)}
              >
                <span className={`stage-marker node-${stage.status}`} />
                <span>
                  <small>
                    {stageName(stage.stage)}
                    {stage.iteration ? ` · 第 ${stage.iteration} 轮` : ''}
                  </small>
                  <strong>{stage.label}</strong>
                </span>
                <span>{nodeStatus(stage.status)}</span>
              </button>
            ))
          ) : (
            <Empty title="等待研究开始">阶段进展会在这里逐步展开。</Empty>
          )}
          {maxIteration > 1 && (
            <button className="text-button" onClick={() => setAllRounds(!allRounds)}>
              {allRounds ? '收起历史轮次' : '展开历史轮次'}
            </button>
          )}
        </section>
        {showGraph && (
          <button className="text-button mobile-list-button" onClick={() => setShowGraph(false)}>
            返回阶段列表
          </button>
        )}
        <Inspector
          run={run}
          node={node}
          events={events}
          historyError={historyError}
          historyLoading={historyLoading}
          hasEarlier={hasEarlier}
          loadEarlier={loadEarlier}
          onOpen={setArtifact}
        />
      </div>
      <section className="saved-artifacts">
        <div className="section-heading">
          <h2>
            阶段成果<span>{run.artifacts?.length ?? 0}</span>
          </h2>
          <span>已保存的版本随时可读</span>
        </div>
        {run.artifacts?.length ? (
          <Artifacts artifacts={run.artifacts} onOpen={setArtifact} />
        ) : (
          <p className="subtle">首份成果保存后会出现在这里。</p>
        )}
      </section>
      {currentArtifact && (
        <ArtifactView
          artifact={currentArtifact}
          runId={run.id}
          resource={artifactResource}
          onClose={() => setArtifact(null)}
        />
      )}
    </main>
  );
}

import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api, clearSubmission, errorText, submissionKey } from './api';
import { Dialog, ErrorNotice } from './components';
import { isTerminal, hasReport } from './format';
import { useSession } from './session';
import type { ResearchRun } from './types';

export function RunActions({
  run,
  onChange,
  allowDelete = false,
}: {
  run: ResearchRun;
  onChange: () => void;
  allowDelete?: boolean;
}) {
  const session = useSession();
  const navigate = useNavigate();
  const [confirm, setConfirm] = useState<'cancel' | 'delete' | 'retry' | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState('');
  const own = session.user?.id === run.user_id;
  const ended = isTerminal(run.status);
  async function act() {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError('');
    try {
      if (confirm === 'cancel') await api.cancel(run.id);
      if (confirm === 'delete') {
        await api.delete(run.id);
        navigate('/history', { replace: true });
      }
      if (confirm === 'retry') {
        const input = { topic: run.topic, instructions: run.instructions ?? '', retry_of: run.id };
        const result = await api.create(input, submissionKey(input));
        clearSubmission();
        navigate(`/research/${result.id}`);
      }
      setConfirm(null);
      onChange();
    } catch (error) {
      setError(errorText(error));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return (
    <>
      <div className="run-actions">
        {hasReport(run.status) && (
          <Link className="button primary" to={`/research/${run.id}/report`}>
            阅读报告
          </Link>
        )}
        {!ended && own && (
          <button
            className="button"
            disabled={run.status === 'cancelling'}
            onClick={() => setConfirm('cancel')}
          >
            {run.status === 'queued'
              ? '取消排队'
              : run.status === 'cancelling'
                ? '正在终止…'
                : '终止生成'}
          </button>
        )}
        {ended && (
          <button className="button" onClick={() => setConfirm('retry')}>
            重新生成
          </button>
        )}
        {ended && own && allowDelete && (
          <button className="text-button danger" onClick={() => setConfirm('delete')}>
            删除
          </button>
        )}
      </div>
      {confirm && (
        <Dialog
          title={
            confirm === 'cancel'
              ? run.status === 'queued'
                ? '取消这项研究？'
                : '终止这项研究？'
              : confirm === 'delete'
                ? '删除这项研究？'
                : '从头重新生成？'
          }
          onClose={() => {
            if (!busy) {
              setConfirm(null);
              setError('');
            }
          }}
        >
          <p className="dialog-copy">
            {confirm === 'cancel'
              ? '已保存的研究成果会保留。终止后，你可以查看或下载已有内容。'
              : confirm === 'delete'
                ? '这项研究的报告、阶段成果与过程记录将被删除，操作无法撤销。'
                : '将使用相同的主题和补充说明创建一项新研究，从头开始生成。当前记录仍然保留。'}
          </p>
          <ErrorNotice message={error} />
          <div className="dialog-actions">
            <button className="button" disabled={busy} onClick={() => setConfirm(null)}>
              返回
            </button>
            <button className="button primary" disabled={busy} onClick={() => void act()}>
              {busy
                ? '正在处理…'
                : confirm === 'cancel'
                  ? '确认终止'
                  : confirm === 'delete'
                    ? '确认删除'
                    : '开始新研究'}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

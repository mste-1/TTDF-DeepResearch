import type { RunEvent, RunStatus } from './types';
export const statusNames: Record<RunStatus, string> = {
  queued: '排队中',
  starting: '准备研究',
  running: '研究中',
  cancelling: '正在终止',
  completed: '已完成',
  completed_with_warnings: '已完成 · 有警告',
  cancelled: '已手动终止',
  failed: '生成失败',
  interrupted: '执行中断',
  timed_out: '已超时',
};
export function isTerminal(status: string) {
  return [
    'completed',
    'completed_with_warnings',
    'cancelled',
    'failed',
    'interrupted',
    'timed_out',
  ].includes(status);
}
export function hasReport(status: string) {
  return status === 'completed' || status === 'completed_with_warnings';
}
export function dateTime(value?: string) {
  return value
    ? new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(value))
    : '—';
}
export function elapsed(start?: string, end?: string) {
  if (!start) return '尚未开始';
  const seconds = Math.max(
    0,
    Math.floor(((end ? new Date(end).getTime() : Date.now()) - new Date(start).getTime()) / 1000),
  );
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
}
const stageNames: Record<string, string> = {
  brief: '研究简报',
  research_brief: '研究简报',
  write_research_brief: '研究简报',
  draft: '初始草稿',
  draft_report: '初始草稿',
  write_draft_report: '初始草稿',
  supervisor: '研究统筹',
  researcher: '专题研究',
  research: '专题研究',
  refine: '草稿修订',
  refinement: '草稿修订',
  refine_draft_report: '草稿修订',
  evaluator: '模型评估',
  evaluation: '模型评估',
  red_team: '红队质疑',
  final: '最终报告',
  final_report: '最终报告',
  final_report_generation: '最终报告',
  summary: '研究摘要',
  compressed_research: '研究成果',
  critique: '质疑与建议',
};
export function stageName(stage: string) {
  return stageNames[stage] ?? '研究阶段';
}
export function nodeStatus(status: string) {
  return (
    (
      {
        pending: '待执行',
        queued: '待执行',
        running: '进行中',
        completed: '已完成',
        skipped: '已跳过',
        failed: '失败',
        cancelled: '已终止',
        interrupted: '已中断',
      } as Record<string, string>
    )[status] ?? '已记录'
  );
}
export function safeExternalUrl(url: string) {
  try {
    const parsed = new URL(url);
    return ['https:', 'http:'].includes(parsed.protocol) ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}
export function eventMessage(event: RunEvent) {
  if (event.message || event.payload?.message || event.data?.message)
    return event.message || event.payload?.message || event.data?.message;
  const label =
    event.payload?.label ||
    event.payload?.title ||
    event.payload?.topic ||
    (event.payload?.stage ? stageName(event.payload.stage) : '研究阶段');
  if (event.type === 'stage.completed' && event.payload?.status === 'failed')
    return `执行失败：${label}`;
  if (event.type === 'stage.completed' && event.payload?.status === 'skipped')
    return `已跳过：${label}`;
  if (event.type === 'stage.completed' && event.payload?.status === 'cancelled')
    return `已终止：${label}`;
  const names: Record<string, string> = {
    'run.queued': '研究已进入等待队列',
    'run.started': '开始研究',
    'run.completed': '完整报告已保存',
    'run.completed_with_warnings': '报告已保存，存在研究警告',
    'run.cancelling': '正在终止研究',
    'run.cancelled': '研究已手动终止',
    'run.failed': '研究执行失败，已保留现有成果',
    'run.interrupted': '研究执行中断，已保留现有成果',
    'stage.started': `开始：${label}`,
    'stage.completed': `完成：${label}`,
    'research.dispatched': `分发研究：${label}`,
    'research.started': `开始研究：${label}`,
    'research.completed': `研究成果已返回：${label}`,
    'artifact.created': `已保存：${label}`,
    'source.discovered': `收录资料：${label}`,
    'quality.evaluated': '模型评估已完成',
    'research.warning': '研究过程中出现警告',
  };
  return names[event.type ?? ''] ?? '研究进展已更新';
}
export function failureMessage(code?: string) {
  return (
    {
      TIMEOUT: '已达到一小时执行时限，本次研究已停止。',
      RESEARCH_FAILED: '研究执行失败，已保存的阶段成果仍可查看和下载。',
      PROCESS_EXITED: '研究执行进程意外退出，已保存的阶段成果仍可查看和下载。',
      WORKER_RESTARTED: '研究服务重启导致本次研究中断，已保存成果仍可查看。',
      WORKER_STOPPED: '研究服务已停止，已保存的阶段成果仍可查看。',
      PROCESS_START_FAILED: '本次研究未能启动，请稍后重新生成。',
      EMPTY_REPORT: '本次研究未生成完整报告，已保存的阶段成果仍可查看。',
    } as Record<string, string>
  )[code ?? ''];
}

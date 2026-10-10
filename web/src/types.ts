export type User = {
  id: string;
  username: string;
  role: 'admin' | 'user';
  must_change_password: boolean;
};
export type Session = { user: User; csrf_token: string };
export type RunStatus =
  | 'queued'
  | 'starting'
  | 'running'
  | 'cancelling'
  | 'completed'
  | 'completed_with_warnings'
  | 'cancelled'
  | 'failed'
  | 'interrupted'
  | 'timed_out';
export type StageNode = {
  id: string;
  label: string;
  stage: string;
  status: string;
  parent_id?: string;
  iteration?: number;
  started_at?: string;
  finished_at?: string;
  source_count?: number;
  message?: string;
};
export type StageEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  kind?: string;
};
export type Artifact = {
  id: string;
  kind: string;
  title: string;
  markdown?: string;
  partial: boolean;
  version: number;
  agent_instance_id?: string;
  created_at: string;
  updated_at?: string;
};
export type ArtifactBody = Artifact & { markdown: string };
export type Source = { url: string; title: string; query?: string; agent_instance_id?: string };
export type RunEvent = {
  seq: number;
  type?: string;
  kind?: string;
  message?: string;
  timestamp?: string;
  created_at?: string;
  agent_instance_id?: string;
  payload?: {
    message?: string;
    label?: string;
    title?: string;
    topic?: string;
    stage?: string;
    status?: string;
    code?: string;
  };
  data?: { message?: string; label?: string; agent_instance_id?: string };
};
export type ResearchRun = {
  id: string;
  user_id: string;
  username?: string;
  topic: string;
  instructions: string;
  status: RunStatus;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  queue_position?: number;
  has_warnings: boolean;
  last_event_seq: number;
  history_available: boolean;
  error_message?: string;
  status_message?: string;
  failure_code?: string;
  warnings?: { message: string }[];
  snapshot: { nodes: StageNode[]; edges: StageEdge[] };
  artifacts: Artifact[];
  sources: Source[];
  events?: RunEvent[];
};
export type RunList = { items: ResearchRun[]; next_cursor?: string | null };
export type NewResearch = { topic: string; instructions: string; retry_of?: string };

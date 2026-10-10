import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import type { Artifact, ArtifactBody } from './types';

export function useArtifact(runId: string, artifact: Artifact | null | undefined) {
  const key = artifact
    ? JSON.stringify([
        runId,
        artifact.id,
        artifact.updated_at ?? artifact.created_at,
        artifact.version,
        artifact.partial,
      ])
    : '';
  const cache = useRef(new Map<string, ArtifactBody>());
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<{
    key: string;
    body: ArtifactBody | null;
    error: string;
    loading: boolean;
  }>({ key: '', body: null, error: '', loading: false });
  const retry = useCallback(() => {
    cache.current.delete(key);
    setRevision((value) => value + 1);
  }, [key]);
  useEffect(() => {
    if (!artifact) {
      setState({ key, body: null, error: '', loading: false });
      return;
    }
    const cached = cache.current.get(key);
    if (cached) {
      setState({ key, body: cached, error: '', loading: false });
      return;
    }
    const controller = new AbortController();
    setState({ key, body: null, error: '', loading: true });
    api
      .artifact(runId, artifact.id, controller.signal)
      .then((body) => {
        if (controller.signal.aborted) return;
        if (typeof body.markdown !== 'string') throw new Error('这份成果的正文暂不可用，请重试。');
        cache.current.set(key, body);
        // Cache is confined to this mounted page; old long reports cannot accumulate indefinitely.
        if (cache.current.size > 20) cache.current.delete(cache.current.keys().next().value!);
        setState({ key, body, error: '', loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({ key, body: null, error: errorText(error), loading: false });
      });
    return () => controller.abort();
  }, [key, revision]);
  const current =
    state.key === key ? state : { key, body: null, error: '', loading: Boolean(artifact) };
  return { body: current.body, loading: current.loading, error: current.error, retry };
}

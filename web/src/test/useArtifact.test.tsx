import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import type { Artifact, ArtifactBody } from '../types';
import { useArtifact } from '../useArtifact';

const artifact: Artifact = {
  id: 'draft-1',
  kind: 'draft',
  title: '初稿',
  partial: false,
  version: 1,
  created_at: '2026-10-10T00:00:00Z',
  updated_at: '2026-10-10T00:00:01Z',
};
describe('on-demand artifact body', () => {
  it('does not fetch before opening, shows loading for a delayed GET, then caches that revision', async () => {
    let resolve: (value: ArtifactBody) => void = () => {};
    const get = vi.spyOn(api, 'artifact').mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const { result, rerender } = renderHook(
      ({ selected }: { selected: Artifact | null }) => useArtifact('run-1', selected),
      { initialProps: { selected: null as Artifact | null } },
    );
    expect(get).not.toHaveBeenCalled();
    rerender({ selected: artifact });
    expect(result.current.loading).toBe(true);
    expect(get).toHaveBeenCalledWith('run-1', 'draft-1', expect.any(AbortSignal));
    await act(async () => resolve({ ...artifact, markdown: '# 已保存初稿' }));
    expect(result.current.body?.markdown).toBe('# 已保存初稿');
    rerender({ selected: null });
    rerender({ selected: { ...artifact } });
    expect(get).toHaveBeenCalledTimes(1);
    expect(result.current.body?.markdown).toBe('# 已保存初稿');
    get.mockResolvedValue({ ...artifact, markdown: '# 更新的初稿' });
    rerender({ selected: { ...artifact, updated_at: '2026-10-10T00:00:02Z' } });
    await act(async () => {});
    expect(get).toHaveBeenCalledTimes(2);
    expect(result.current.body?.markdown).toBe('# 更新的初稿');
  });
  it('presents a body-load error and permits an explicit retry', async () => {
    const get = vi.spyOn(api, 'artifact').mockRejectedValue(new Error('读取成果失败'));
    const { result } = renderHook(() => useArtifact('run-1', artifact));
    await act(async () => {});
    expect(result.current.error).toBe('读取成果失败');
    expect(result.current.loading).toBe(false);
    get.mockResolvedValue({ ...artifact, markdown: '重新读取成功' });
    await act(async () => result.current.retry());
    expect(result.current.error).toBe('');
    expect(result.current.body?.markdown).toBe('重新读取成功');
  });
  it('aborts the old GET and cannot show a late response from a previously selected artifact', async () => {
    let oldResolve: (value: ArtifactBody) => void = () => {};
    const get = vi
      .spyOn(api, 'artifact')
      .mockImplementationOnce(
        () =>
          new Promise((done) => {
            oldResolve = done;
          }),
      )
      .mockResolvedValue({ ...artifact, id: 'draft-2', markdown: '第二份成果' });
    const { result, rerender } = renderHook(({ selected }) => useArtifact('run-1', selected), {
      initialProps: { selected: artifact },
    });
    const oldSignal = get.mock.calls[0][2]!;
    rerender({ selected: { ...artifact, id: 'draft-2' } });
    await act(async () => {});
    expect(oldSignal.aborted).toBe(true);
    await act(async () => oldResolve({ ...artifact, markdown: '旧响应' }));
    expect(result.current.body?.markdown).toBe('第二份成果');
  });
});

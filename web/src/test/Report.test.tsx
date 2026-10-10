import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Report, ReportContents } from '../Report';
import { api } from '../api';

afterEach(() => vi.unstubAllGlobals());
describe('report table of contents', () => {
  it('downloads the clean final report through its dedicated endpoint', async () => {
    const artifact = {
      id: 'artifact-final',
      kind: 'final',
      title: '最终报告',
      version: 1,
      partial: false,
      created_at: '2026-10-10T00:00:00Z',
    };
    vi.spyOn(api, 'run').mockResolvedValue({
      id: 'run-1',
      user_id: 'user-1',
      topic: '研究报告',
      instructions: '',
      status: 'completed',
      created_at: '2026-10-10T00:00:00Z',
      has_warnings: false,
      last_event_seq: 1,
      history_available: true,
      snapshot: { nodes: [], edges: [] },
      artifacts: [artifact],
      sources: [],
    });
    vi.spyOn(api, 'history').mockResolvedValue({ items: [], history_available: true });
    vi.spyOn(api, 'artifact').mockResolvedValue({ ...artifact, markdown: '# 最终报告正文' });
    render(
      <MemoryRouter initialEntries={['/research/run-1/report']}>
        <Routes>
          <Route path="/research/:runId/report" element={<Report />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole('link', { name: '下载 Markdown ↓' })).toHaveAttribute(
      'href',
      '/api/v1/research-runs/run-1/report.md',
    );
  });
  it('starts collapsed on mobile, allows manual opening, and responds to desktop width', () => {
    let listener: (event: { matches: boolean }) => void = () => {};
    vi.stubGlobal(
      'matchMedia',
      vi.fn().mockReturnValue({
        matches: false,
        addEventListener: (_: string, callback: typeof listener) => {
          listener = callback;
        },
        removeEventListener: vi.fn(),
      }),
    );
    const { container } = render(
      <ReportContents headings={[{ id: 'section', text: '研究结论', level: 1 }]} />,
    );
    const details = container.querySelector('details')!;
    expect(details.open).toBe(false);
    fireEvent.click(screen.getByText('章节目录'));
    expect(details.open).toBe(true);
    act(() => listener({ matches: true }));
    expect(details.open).toBe(true);
    act(() => listener({ matches: false }));
    expect(details.open).toBe(false);
  });
});

import { render, screen } from '@testing-library/react';
import { StrictMode } from 'react';
import { describe, expect, it } from 'vitest';
import { Markdown, markdownHeadings } from '../Markdown';
import { ReportContents } from '../Report';

describe('untrusted research Markdown', () => {
  it('renders useful report structure without executing HTML or tracking images', () => {
    const { container } = render(
      <Markdown
        content={
          '# 研究结论\n\n<script>alert(1)</script>\n\n[危险](javascript:alert%281%29)\n\n[资料](https://example.com/report)\n\n![remote](https://example.com/tracker.png)\n\n| 方案 | 结论 |\n| --- | --- |\n| A | 可行 |'
        }
      />,
    );
    expect(screen.getByRole('heading', { name: '研究结论' })).toBeInTheDocument();
    expect(screen.getByRole('table')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('危险').closest('a')).toBeNull();
    expect(screen.getByRole('link', { name: '资料' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    );
  });
  it('gives repeated headings distinct matching TOC links and ignores fenced headings', () => {
    const text = '# 总览\n\n## 比较\n\n```md\n# not a heading\n```\n\n## 比较';
    const toc = markdownHeadings(text);
    const { container } = render(<Markdown content={text} />);
    expect(toc).toHaveLength(3);
    expect(new Set(toc.map((item) => item.id)).size).toBe(3);
    for (const entry of toc)
      expect(container.querySelector(`[id="${entry.id}"]`)).toHaveTextContent(entry.text);
  });
  it('keeps every TOC target deterministic under StrictMode with CommonMark headings and inline formatting', () => {
    const markdown = [
      '# 城市通勤方式比较',
      '',
      '## **摘要** 与 [资料](https://example.com)',
      '',
      '```markdown',
      '# 代码内不是目录',
      '```',
      '',
      '~~~text',
      '## 另一种围栏内不是目录',
      '~~~',
      '',
      '## 重复标题',
      '',
      '## 重复标题',
      '',
      'Setext *一级标题*',
      '================',
      '',
      'Setext `二级标题`',
      '----------------',
      '',
      '### ~~旧方案~~ 与新方案 &amp; 比较',
      '',
      '#### 四级细节不进入三级章节目录',
    ].join('\n');
    const toc = markdownHeadings(markdown);
    expect(toc.map((item) => item.text)).toEqual([
      '城市通勤方式比较',
      '摘要 与 资料',
      '重复标题',
      '重复标题',
      'Setext 一级标题',
      'Setext 二级标题',
      '旧方案 与新方案 & 比较',
    ]);
    const tree = (
      <StrictMode>
        <ReportContents headings={toc} />
        <Markdown content={markdown} />
      </StrictMode>
    );
    const { container, rerender } = render(tree);
    function assertTargets() {
      const links = container.querySelectorAll<HTMLAnchorElement>('.report-toc a');
      expect(links).toHaveLength(toc.length);
      for (const link of links) {
        const targets = container.querySelectorAll(`[id="${link.hash.slice(1)}"]`);
        expect(targets).toHaveLength(1);
        expect(targets[0].tagName).toMatch(/^H[123]$/);
        expect(targets[0]).toHaveTextContent(link.textContent!);
      }
    }
    assertTargets();
    const ids = Array.from(
      container.querySelectorAll('.markdown h1, .markdown h2, .markdown h3'),
      (node) => node.id,
    );
    rerender(
      <StrictMode>
        <ReportContents headings={[...toc]} />
        <Markdown content={markdown} />
      </StrictMode>,
    );
    assertTargets();
    expect(
      Array.from(
        container.querySelectorAll('.markdown h1, .markdown h2, .markdown h3'),
        (node) => node.id,
      ),
    ).toEqual(ids);
  });
});

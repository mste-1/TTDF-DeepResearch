import { type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Element } from 'hast';
import type { Heading, Nodes } from 'mdast';
import { toString } from 'mdast-util-to-string';
import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import rehypeSanitize from 'rehype-sanitize';
import { unified } from 'unified';
import { safeExternalUrl } from './format';

const headingParser = unified().use(remarkParse).use(remarkGfm);
function headingId(offset: number | undefined) {
  return offset === undefined ? undefined : `section-${offset}`;
}
export function markdownHeadings(markdown: string) {
  const headings: Heading[] = [];
  function visit(node: Nodes) {
    if (node.type === 'heading' && node.depth <= 3) headings.push(node);
    if ('children' in node) node.children.forEach(visit);
  }
  visit(headingParser.parse(markdown));
  return headings.flatMap((node) => {
    const id = headingId(node.position?.start.offset);
    return id ? [{ id, text: toString(node), level: node.depth }] : [];
  });
}
export function Markdown({ content }: { content: string }) {
  // Both mdast (TOC) and the rendered hast node retain the same source position.
  // No render-time counters: StrictMode, repeated titles and rerenders cannot change the ID.
  const heading = (Tag: 'h1' | 'h2' | 'h3', node: Element | undefined, children: ReactNode) => (
    <Tag id={headingId(node?.position?.start.offset)}>{children}</Tag>
  );
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeSanitize]}
        skipHtml
        components={{
          h1: ({ node, children }) => heading('h1', node, children),
          h2: ({ node, children }) => heading('h2', node, children),
          h3: ({ node, children }) => heading('h3', node, children),
          a: ({ href, children }) =>
            href?.startsWith('#') ? (
              <a href={href}>{children}</a>
            ) : safeExternalUrl(href ?? '') ? (
              <a href={safeExternalUrl(href!)} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ alt }) => (
            <span className="image-placeholder">{alt ? `[图片：${alt}]` : '[图片]'}</span>
          ),
          table: ({ children }) => (
            <div className="table-scroll">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

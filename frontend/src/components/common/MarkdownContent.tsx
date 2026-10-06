import {
  Component,
  memo,
  type ReactNode,
} from "react";
import ReactMarkdown, { type Options as ReactMarkdownOptions } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { normalizeMathDelimiters } from "@/lib/markdown";

// Single, mainstream Markdown rendering pipeline shared by the chat surface
// and the swarm run/analysis views:
//   react-markdown + remark-gfm (tables / task lists / strikethrough)
//   + remark-math/rehype-katex (formulas) + rehype-highlight (code blocks)
//   + Tailwind Typography prose styling (borders, headings, table rhythm).
//
// singleDollarTextMath off: dollar amounts ("$150 to $120") must never parse
// as formulas; LLM \(...\)/\[...\] delimiters are normalized to $$ first.
const remarkPlugins: ReactMarkdownOptions["remarkPlugins"] = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
];
const rehypePlugins: ReactMarkdownOptions["rehypePlugins"] = [
  rehypeHighlight,
  rehypeKatex,
];

const markdownComponents: ReactMarkdownOptions["components"] = {
  table: ({ node, ...props }) => {
    void node;
    // Fit the page width and wrap cell text instead of forcing horizontal
    // scrolling; GFM column alignment is preserved by the cell text-align.
    return (
      <div className="min-w-0 max-w-full">
        <table className="w-full table-fixed" {...props} />
      </div>
    );
  },
  a: ({ node, ...props }) => {
    void node;
    return <a {...props} target="_blank" rel="noopener noreferrer" />;
  },
};

// Normalized business-document typography. Tables get explicit borders,
// header background, cell padding and left-aligned headers; GFM column
// alignment is preserved natively by the rendered align attribute.
//
// Every element wraps to the page width: long words/URLs break (break-words),
// fenced code blocks wrap instead of scrolling (pre-wrap + overflow-wrap:
// anywhere), and fixed-layout tables wrap cell text. min-w-0 lets the prose
// shrink inside flex/grid parents.
const proseClassName =
  "prose prose-sm dark:prose-invert max-w-none min-w-0 break-words " +
  "text-[15px] leading-relaxed " +
  "prose-p:font-serif prose-p:text-[15.5px] prose-p:leading-[1.75] " +
  "prose-li:font-serif prose-li:text-[15.5px] prose-li:leading-[1.75] " +
  "prose-headings:font-sans prose-table:font-sans prose-code:font-mono " +
  "prose-blockquote:font-sans [&_blockquote_p]:font-sans " +
  "prose-table:border prose-table:border-border/50 " +
  "prose-th:bg-muted/30 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 " +
  "prose-th:text-left prose-th:text-xs prose-th:font-medium prose-td:text-xs " +
  "[&_th]:align-top [&_td]:align-top " +
  "[&_pre]:whitespace-pre-wrap [&_pre]:[overflow-wrap:anywhere] " +
  "[&_pre]:overflow-x-hidden [&_code]:[overflow-wrap:anywhere] " +
  "prose-hr:hidden";

interface MarkdownErrorBoundaryProps {
  content: string;
  children: ReactNode;
}

interface MarkdownErrorBoundaryState {
  failed: boolean;
}

export class MarkdownErrorBoundary extends Component<
  MarkdownErrorBoundaryProps,
  MarkdownErrorBoundaryState
> {
  state: MarkdownErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): MarkdownErrorBoundaryState {
    return { failed: true };
  }

  componentDidUpdate(previous: MarkdownErrorBoundaryProps) {
    if (this.state.failed && previous.content !== this.props.content) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return <span className="whitespace-pre-wrap break-words">{this.props.content}</span>;
    }
    return this.props.children;
  }
}

export interface MarkdownContentProps {
  content: string;
  /** Streaming content skips the heavy rehype plugins (highlight/katex). */
  streaming?: boolean;
  showCursor?: boolean;
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  streaming = false,
  showCursor = false,
}: MarkdownContentProps) {
  let normalized = content;
  try {
    normalized = normalizeMathDelimiters(content);
  } catch {
    normalized = content;
  }

  return (
    <div className={proseClassName}>
      <MarkdownErrorBoundary content={content}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={streaming ? [] : rehypePlugins}
          components={markdownComponents}
        >
          {normalized}
        </ReactMarkdown>
      </MarkdownErrorBoundary>
      {showCursor && (
        <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
      )}
    </div>
  );
});

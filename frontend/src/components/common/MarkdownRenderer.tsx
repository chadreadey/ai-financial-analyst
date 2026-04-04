import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  content: string;
}

export function MarkdownRenderer({ content }: Props) {
  return (
    <div className="prose prose-invert max-w-none text-sm leading-relaxed"
      style={{ color: "var(--text-primary)" }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        children={content}
        components={{
          h1: ({ children }) => <h1 className="text-xl font-bold mt-6 mb-3" style={{ color: "var(--text-primary)" }}>{children}</h1>,
          h2: ({ children }) => <h2 className="text-lg font-semibold mt-5 mb-2" style={{ color: "var(--text-primary)" }}>{children}</h2>,
          h3: ({ children }) => <h3 className="text-base font-semibold mt-4 mb-2" style={{ color: "var(--text-primary)" }}>{children}</h3>,
          p: ({ children }) => <p className="mb-3" style={{ color: "var(--text-secondary)" }}>{children}</p>,
          li: ({ children }) => <li className="mb-1" style={{ color: "var(--text-secondary)" }}>{children}</li>,
          strong: ({ children }) => <strong style={{ color: "var(--text-primary)" }}>{children}</strong>,
          code: ({ children, className }) => {
            const isBlock = className?.includes("language-");
            if (isBlock) {
              return (
                <pre className="rounded-md p-3 overflow-x-auto text-xs my-3"
                  style={{ background: "var(--bg-primary)" }}>
                  <code>{children}</code>
                </pre>
              );
            }
            return (
              <code className="px-1 py-0.5 rounded text-xs"
                style={{ background: "var(--bg-hover)", color: "var(--accent-blue)" }}>
                {children}
              </code>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto my-3">
              <table className="w-full text-xs" style={{ borderColor: "var(--border)" }}>
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="text-left px-3 py-2 font-semibold border-b"
              style={{ borderColor: "var(--border)", color: "var(--text-primary)" }}>
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="px-3 py-2 border-b"
              style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}>
              {children}
            </td>
          ),
        }}
      />
    </div>
  );
}

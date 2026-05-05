import { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface Props {
  role: "user" | "agent";
  text: string;
  index?: number;
  meta?: ReactNode;
  footer?: ReactNode;
  streaming?: boolean;
}

function formatIndex(n: number): string {
  return n.toString().padStart(3, "0");
}

export default function MessageBubble({
  role,
  text,
  index,
  meta,
  footer,
  streaming = false,
}: Props) {
  if (role === "user") {
    return (
      <article className="flex gap-4 animate-fade-up">
        <div className="hidden sm:block w-12 shrink-0 pt-1 text-right">
          <div className="font-mono text-[10px] uppercase tracking-section text-ink-3">
            ASK
          </div>
          {index !== undefined && (
            <div className="font-mono text-[10px] text-ink-4 mt-0.5">
              №{formatIndex(index)}
            </div>
          )}
        </div>
        <div className="flex-1 border-l-2 border-ink pl-4 py-1">
          <p
            className="font-display text-[20px] leading-snug tracking-tight text-ink"
            style={{ fontVariationSettings: '"SOFT" 50, "WONK" 0, "opsz" 48' }}
          >
            {text}
          </p>
        </div>
      </article>
    );
  }

  return (
    <article className="flex gap-4 animate-fade-up">
      <div className="hidden sm:block w-12 shrink-0 pt-1 text-right">
        <div className="font-mono text-[10px] uppercase tracking-section text-oxblood">
          REPLY
        </div>
        {index !== undefined && (
          <div className="font-mono text-[10px] text-ink-4 mt-0.5">
            №{formatIndex(index)}
          </div>
        )}
      </div>
      <div className="flex-1 surface px-5 py-4">
        {meta && (
          <div className="border-b border-rule pb-2 mb-3 text-[11px] text-ink-3">
            {meta}
          </div>
        )}
        <div className={`report-md ${streaming ? "caret" : ""}`}>
          {text ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          ) : (
            <span className="text-ink-3 italic font-display">drafting…</span>
          )}
        </div>
        {footer && (
          <div className="border-t border-rule pt-3 mt-4">{footer}</div>
        )}
      </div>
    </article>
  );
}

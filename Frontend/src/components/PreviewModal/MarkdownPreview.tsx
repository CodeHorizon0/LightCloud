import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import styles from "./PreviewModal.module.css";

export default function MarkdownPreview({ source }: { source: string }) {
  return (
    <div className={styles.previewMarkdown}>
      <ReactMarkdown
        skipHtml
        remarkPlugins={[remarkGfm]}
        disallowedElements={["img"]}
        unwrapDisallowed
        components={{
          a({ children }) {
            return <span>{children}</span>;
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}

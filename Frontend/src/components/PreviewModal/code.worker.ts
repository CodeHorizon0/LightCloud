import { createLowlight } from "lowlight";
import type { LanguageFn } from "highlight.js";
import type { RootContent } from "hast";
import type { CodeLine, CodeRequest, CodeResult } from "./codeTypes";

const loaders: Partial<Record<string, () => Promise<{ default: LanguageFn }>>> =
  {
    python: function load() {
      return import("highlight.js/lib/languages/python");
    },
    javascript: function load() {
      return import("highlight.js/lib/languages/javascript");
    },
    typescript: function load() {
      return import("highlight.js/lib/languages/typescript");
    },
    json: function load() {
      return import("highlight.js/lib/languages/json");
    },
    css: function load() {
      return import("highlight.js/lib/languages/css");
    },
    scss: function load() {
      return import("highlight.js/lib/languages/scss");
    },
    less: function load() {
      return import("highlight.js/lib/languages/less");
    },
    xml: function load() {
      return import("highlight.js/lib/languages/xml");
    },
    cpp: function load() {
      return import("highlight.js/lib/languages/cpp");
    },
    csharp: function load() {
      return import("highlight.js/lib/languages/csharp");
    },
    java: function load() {
      return import("highlight.js/lib/languages/java");
    },
    go: function load() {
      return import("highlight.js/lib/languages/go");
    },
    rust: function load() {
      return import("highlight.js/lib/languages/rust");
    },
    bash: function load() {
      return import("highlight.js/lib/languages/bash");
    },
    powershell: function load() {
      return import("highlight.js/lib/languages/powershell");
    },
    sql: function load() {
      return import("highlight.js/lib/languages/sql");
    },
    yaml: function load() {
      return import("highlight.js/lib/languages/yaml");
    },
    ini: function load() {
      return import("highlight.js/lib/languages/ini");
    },
    ruby: function load() {
      return import("highlight.js/lib/languages/ruby");
    },
    php: function load() {
      return import("highlight.js/lib/languages/php");
    },
    swift: function load() {
      return import("highlight.js/lib/languages/swift");
    },
    kotlin: function load() {
      return import("highlight.js/lib/languages/kotlin");
    },
    lua: function load() {
      return import("highlight.js/lib/languages/lua");
    },
    r: function load() {
      return import("highlight.js/lib/languages/r");
    },
    dos: function load() {
      return import("highlight.js/lib/languages/dos");
    },
    dockerfile: function load() {
      return import("highlight.js/lib/languages/dockerfile");
    },
    makefile: function load() {
      return import("highlight.js/lib/languages/makefile");
    },
  };
const lowlight = createLowlight();
const controlKeywords = new Set([
  "if",
  "else",
  "elif",
  "elseif",
  "endif",
  "for",
  "foreach",
  "while",
  "do",
  "switch",
  "case",
  "default",
  "break",
  "continue",
  "return",
  "try",
  "catch",
  "except",
  "finally",
  "throw",
  "throws",
  "raise",
  "yield",
  "await",
  "async",
  "import",
  "from",
  "export",
  "package",
  "using",
  "namespace",
  "goto",
  "match",
  "with",
  "defer",
]);

function tokenize(nodes: RootContent[]): CodeLine[] {
  const lines: CodeLine[] = [[]];
  let count = 0;
  function visit(node: RootContent, classes: string, depth: number): void {
    if (depth > 100) throw new Error("Code nesting limit");
    if (node.type === "text") {
      const parts = node.value.split("\n");
      for (let index = 0; index < parts.length; index += 1) {
        if (index) lines.push([]);
        if (!parts[index]) continue;
        count += 1;
        if (count > 40000) throw new Error("Code token limit");
        const text = parts[index];
        const scope =
          classes.includes("hljs-keyword") &&
          controlKeywords.has(text.toLowerCase())
            ? `${classes} hljs-control`
            : classes;
        lines[lines.length - 1].push({ text, classes: scope });
      }
    } else if (node.type === "element") {
      const own = Array.isArray(node.properties.className)
        ? node.properties.className
        : [];
      const safe = own
        .filter(function valid(value) {
          return (
            typeof value === "string" && /^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(value)
          );
        })
        .join(" ");
      for (const child of node.children)
        visit(child, safe || classes, depth + 1);
    }
  }
  for (const node of nodes) visit(node, "", 0);
  return lines;
}

self.onmessage = async function highlight(event: MessageEvent<CodeRequest>) {
  let lines: CodeLine[] | null = null;
  try {
    const loader = loaders[event.data.language];
    if (loader) {
      const dependencies: Record<string, string[]> = {
        javascript: ["xml"],
        typescript: ["xml"],
        xml: ["javascript", "css"],
        php: ["xml", "javascript", "css"],
      };
      await Promise.all(
        [event.data.language, ...(dependencies[event.data.language] ?? [])].map(
          async function register(language) {
            const load = loaders[language];
            if (load) lowlight.register(language, (await load()).default);
          },
        ),
      );
      lines = tokenize(
        lowlight.highlight(event.data.language, event.data.source).children,
      );
    }
  } catch {
    lines = null;
  }
  self.postMessage({ lines } satisfies CodeResult);
};

import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

function publicFiles(directory: string): string[] {
  const files: string[] = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isFile()) files.push(path);
    else if (entry.isDirectory()) files.push(...publicFiles(path));
  }
  return files.sort();
}

export function pwa(): Plugin {
  return {
    name: "lightcloud-pwa",
    apply: "build",
    enforce: "post",
    generateBundle(_, bundle) {
      const publicDir = fileURLToPath(new URL("../public/", import.meta.url));
      const assets = Object.keys(bundle).map(function (name) {
        return `/${name}`;
      });
      const hash = createHash("sha256");
      for (const name of Object.keys(bundle).sort()) {
        const item = bundle[name];
        hash.update(name);
        hash.update(item.type === "chunk" ? item.code : item.source);
      }
      for (const full of publicFiles(publicDir)) {
        const path = relative(publicDir, full).replaceAll("\\", "/");
        assets.push(`/${path}`);
        hash.update(path).update(readFileSync(full));
      }
      const template = readFileSync(
        new URL("./service-worker.js", import.meta.url),
        "utf8",
      );
      hash.update(template);
      this.emitFile({
        type: "asset",
        fileName: "sw.js",
        source: template
          .replace("__BUILD_VERSION__", hash.digest("hex").slice(0, 20))
          .replace(
            '"__PRECACHE_ASSETS__"',
            JSON.stringify(JSON.stringify(assets.sort())),
          ),
      });
    },
  };
}

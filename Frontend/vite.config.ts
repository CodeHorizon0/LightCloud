import { pwa } from "./build/pwa";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(function configure({ mode }) {
  const env = loadEnv(mode, process.cwd(), "LIGHTCLOUD_");
  const proxy = {
    "/api/": {
      target: env.LIGHTCLOUD_PROXY_TARGET || "http://127.0.0.1:3000",
      rewrite(path: string) {
        return path.slice(4);
      },
    },
  };

  return {
    plugins: [react(), pwa()],
    worker: { format: "es" },
    optimizeDeps: {
      entries: ["index.html", "src/components/PreviewModal/code.worker.ts"],
      exclude: [
        "@silurus/ooxml",
        "@silurus/ooxml/docx",
        "@silurus/ooxml/xlsx",
        "@silurus/ooxml/pptx",
      ],
    },
    server: { host: "localhost", strictPort: true, proxy },
    preview: { host: "localhost", strictPort: true, proxy },
  };
});

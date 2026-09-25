import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// One self-contained ES module plus one stylesheet, served by the host from the
// installed package (`assets-v1`). No shared host React: everything is bundled.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    outDir: "../deerflow_extension_context_residency/static/dist",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
    cssCodeSplit: false,
    minify: "esbuild",
    lib: {
      entry: "src/index.ts",
      formats: ["es"],
      fileName: () => "index.mjs",
      cssFileName: "styles",
    },
    rollupOptions: {
      output: {
        chunkFileNames: "chunks/[name].mjs",
        assetFileNames: "[name][extname]",
      },
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
  },
});

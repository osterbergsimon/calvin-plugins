import { defineConfig } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const entry = process.env.CALVIN_PLUGIN_ENTRY;
const outDir = process.env.CALVIN_PLUGIN_OUTDIR;
const fileName = process.env.CALVIN_PLUGIN_DIST_NAME || "dist.js";

if (!entry) {
  throw new Error("CALVIN_PLUGIN_ENTRY must point to a plugin frontend source entry");
}

if (!outDir) {
  throw new Error("CALVIN_PLUGIN_OUTDIR must point to a plugin frontend output directory");
}

function singleFileOnly() {
  return {
    name: "calvin-plugin-single-file-only",
    generateBundle(_options, bundle) {
      const assets = Object.values(bundle).filter((chunk) => chunk.type === "asset");
      if (assets.length > 0) {
        const names = assets.map((asset) => asset.fileName).join(", ");
        this.error(`Plugin frontends must build to one JavaScript module; emitted assets: ${names}`);
      }
    },
  };
}

export default defineConfig({
  root: repoRoot,
  publicDir: false,
  build: {
    emptyOutDir: false,
    outDir,
    sourcemap: false,
    minify: false,
    cssCodeSplit: false,
    lib: {
      entry,
      formats: ["es"],
      fileName: () => fileName,
    },
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        generatedCode: {
          constBindings: true,
        },
      },
    },
  },
  plugins: [singleFileOnly()],
});

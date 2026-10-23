// Serve the barcode reader's WebAssembly from our own origin (public/zxing/) instead of the
// CDN the polyfill would fetch it from. Runs before `dev` and `build`.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const fromDetector = createRequire(createRequire(import.meta.url).resolve("barcode-detector"));
const wasm = fromDetector.resolve("zxing-wasm/reader/zxing_reader.wasm");
const out = join(here, "..", "public", "zxing");
mkdirSync(out, { recursive: true });
copyFileSync(wasm, join(out, "zxing_reader.wasm"));

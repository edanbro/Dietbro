/**
 * Reading product barcodes from the camera. The browser's own BarcodeDetector where it has one
 * (Chrome on Android and macOS); elsewhere (Windows Chrome/Edge, iOS Safari, Firefox) the
 * `barcode-detector` polyfill, loaded only when scanning starts, with its WebAssembly reader
 * served from our own origin (public/zxing, copied by scripts/copy-zxing.mjs) instead of a CDN.
 */

export const PRODUCT_FORMATS = ["ean_13", "ean_8", "upc_a", "upc_e"] as const;
export const ZXING_WASM_URL = "/zxing/zxing_reader.wasm";

export type Detector = {
  detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]>;
};

type NativeDetectorClass = {
  new (options: { formats: string[] }): Detector;
  getSupportedFormats(): Promise<string[]>;
};

export async function createDetector(): Promise<Detector> {
  const native = (globalThis as { BarcodeDetector?: NativeDetectorClass }).BarcodeDetector;
  if (native) {
    try {
      const supported = await native.getSupportedFormats();
      const formats = PRODUCT_FORMATS.filter((f) => supported.includes(f));
      if (formats.length) return new native({ formats: [...formats] });
    } catch {
      // fall through to the polyfill
    }
  }
  const { BarcodeDetector, setZXingModuleOverrides } = await import("barcode-detector/ponyfill");
  setZXingModuleOverrides({
    locateFile: (path: string, prefix: string) =>
      path.endsWith(".wasm") ? ZXING_WASM_URL : prefix + path,
  });
  return new BarcodeDetector({ formats: [...PRODUCT_FORMATS] });
}

/** Digits only; null unless 8, 12, 13 or 14 of them (the API checks the check digit). */
export function cleanBarcode(text: string): string | null {
  const digits = text.replace(/\D/g, "");
  return [8, 12, 13, 14].includes(digits.length) ? digits : null;
}

/**
 * Barcode scanner using ZXing library.
 *
 * Detects Code 128 / Code 39 barcodes from the device camera.
 */

import {
  BrowserMultiFormatReader,
  BarcodeFormat,
  DecodeHintType,
} from "@zxing/library";

const MAC_RE = /^[0-9A-Fa-f]{12}$/;

/**
 * Classify a scanned value as either "mac" or "password".
 * MAC barcodes encode exactly 12 hex characters.
 */
export function classifyBarcode(value) {
  const cleaned = value.replace(/[:\- ]/g, "");
  if (MAC_RE.test(cleaned)) {
    return { type: "mac", value: cleaned.toUpperCase() };
  }
  return { type: "password", value };
}

/**
 * Format a raw 12-char hex MAC into colon-separated form.
 */
export function formatMac(raw) {
  const hex = raw.replace(/[:\- ]/g, "").toUpperCase();
  return hex.match(/.{2}/g)?.join(":") || hex;
}

/**
 * Start scanning barcodes from the camera.
 *
 * @param {HTMLVideoElement} videoEl - The <video> element to use as preview.
 * @param {(result: {type: string, value: string}) => void} onResult - Callback when barcode decoded.
 * @returns {{ stop: () => void }} Controller to stop scanning.
 */
export function startScanner(videoEl, onResult) {
  const hints = new Map();
  hints.set(DecodeHintType.POSSIBLE_FORMATS, [
    BarcodeFormat.CODE_128,
    BarcodeFormat.CODE_39,
    BarcodeFormat.QR_CODE,
  ]);

  const reader = new BrowserMultiFormatReader(hints);
  let stopped = false;

  reader
    .decodeFromVideoDevice(undefined, videoEl, (result, error) => {
      if (stopped) return;
      if (result) {
        const classified = classifyBarcode(result.getText());
        onResult(classified);
      }
      // Ignore decode errors (no barcode in frame)
    })
    .catch((err) => {
      if (!stopped) {
        console.error("Scanner error:", err);
      }
    });

  return {
    stop() {
      stopped = true;
      reader.reset();
    },
  };
}

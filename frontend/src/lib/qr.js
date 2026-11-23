import qrcode from 'qrcode-generator';

/** A QR code for text as an image data URL (works under the app's CSP: img-src data:). */
export function qrDataUrl(text, cellSize = 6) {
  const qr = qrcode(0, 'M'); // smallest size that fits, medium error correction (scans well off a laptop screen)
  qr.addData(text);
  qr.make();
  return qr.createDataURL(cellSize, 2);
}

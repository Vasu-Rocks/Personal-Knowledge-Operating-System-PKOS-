// Regenerates the PDF fixtures in this folder with Chromium's PDF printer (the Electron in desktop/):
//   desktop\node_modules\electron\dist\electron.exe backend\tests\data\make_pdf_fixtures.js backend\tests\data
// Chromium-made PDFs matter: their glyphs are positioned individually, which is what exposed PDFium's lost spaces.
// (password.pdf is made separately and is not listed here: it is the image_then_text page encrypted with the password "secret".)
const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const out = path.resolve(process.argv[2] || __dirname);
const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'pkos-fixtures-'));

let seed = 99;
const rnd = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
const pick = (a) => a[Math.floor(rnd() * a.length)];
const css = "<style>body{font:11pt/1.45 'Segoe UI',Arial,sans-serif;margin:0} p{margin:0 0 9pt;text-align:justify}</style>";
const page = (body) => `<!doctype html><html lang="en"><head><meta charset="utf-8">${css}</head><body>${body}</body></html>`;

const WORDS = 'the quick brown fox jumps over the lazy dog while sensors record temperature and humidity near the glacier'.split(' ');
const sentence = (n) => `S${String(n).padStart(3, '0')} ${Array.from({ length: 9 }, () => pick(WORDS)).join(' ')}.`;

let n = 1;
const prose = Array.from({ length: 130 }, () => `<p>${[0, 1, 2, 3].map(() => sentence(n++)).join(' ')}</p>`).join('');
const rows = Array.from({ length: 25 }, (_, i) => `<tr><td>R${String(i + 1).padStart(3, '0')}</td><td>${pick(['Aletsch', 'Pasterze', 'Rhone', 'Mer de Glace'])}</td><td>${(rnd() * 8 - 4).toFixed(1)}</td><td>${Math.floor(rnd() * 400)}</td></tr>`).join('');
const table = `<table border="1" cellspacing="0" cellpadding="3" style="border-collapse:collapse;width:100%"><tr><th>ID</th><th>Site</th><th>Temp</th><th>Ice</th></tr>${rows}</table>`;
const svg = '<svg width="400" height="400" xmlns="http://www.w3.org/2000/svg"><circle cx="200" cy="200" r="150" fill="steelblue"/></svg>';

const docs = [
  { name: 'prose_headers', html: page(prose), header: true },
  { name: 'table_page', html: page(table), header: false },
  { name: 'image_then_text', html: page(`<div style="page-break-after:always">${svg}</div><p>${sentence(1)} ${sentence(2)} ${sentence(3)}</p>`), header: false },
];
const HEADER = '<div style="font-size:9px;width:100%;text-align:center">Alpine Glacier Monitoring Handbook</div>';
const FOOTER = '<div style="font-size:9px;width:100%;text-align:center">Page <span class="pageNumber"></span> of <span class="totalPages"></span></div>';

app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  for (const d of docs) {
    const file = path.join(tmp, `${d.name}.html`);
    fs.writeFileSync(file, d.html, 'utf8');
    await win.loadURL(pathToFileURL(file).toString());
    await new Promise((r) => setTimeout(r, 300));
    const pdf = await win.webContents.printToPDF({
      pageSize: 'Letter', printBackground: true, displayHeaderFooter: d.header, headerTemplate: HEADER, footerTemplate: FOOTER,
      margins: { top: 0.9, bottom: 0.9, left: 0.9, right: 0.9 },
    });
    fs.writeFileSync(path.join(out, `${d.name}.pdf`), pdf);
    console.log(`${d.name}.pdf ${(pdf.length / 1024).toFixed(0)} KB`);
  }
  win.destroy();
  app.quit();
});

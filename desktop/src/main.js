'use strict';
// PKOS desktop: Electron main process. Starts the local services, then shows the React UI from the app:// protocol.
const path = require('path');
const fs = require('fs');
const { app, BrowserWindow, clipboard, dialog, ipcMain, net, protocol, safeStorage, shell } = require('electron');
const { pathToFileURL } = require('url');
const { resolvePaths } = require('./paths');
const { isUpgrade, loadOrCreateConfig, updateConfig } = require('./config');
const { Supervisor } = require('./services');
const { openLog } = require('./process');
const { BackupManager } = require('./backup');
const { collectDiagnostics } = require('./diagnostics');

const isDev = !app.isPackaged || process.argv.includes('--dev');
const paths = resolvePaths({ packaged: app.isPackaged && !process.argv.includes('--dev'), resourcesPath: process.resourcesPath });
const APP_ORIGIN = 'app://pkos';

// Electron's own data (cache, local storage) goes next to the vault instead of roaming %APPDATA%.
app.setPath('userData', paths.electronData);
protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

let desktopLog = { write: () => {} };
let splash = null;
let mainWindow = null;
let supervisor = null;
let backups = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    const win = mainWindow || splash;
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
  app.whenReady().then(boot);
}

// ------------------------------------------------------------------------------------------- web content

function csp() {
  const api = supervisor && supervisor.backend.url ? supervisor.backend.url : 'http://127.0.0.1:*';
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "worker-src 'self' blob:",
    `connect-src 'self' ${api}`,
    "object-src 'none'",
    "base-uri 'none'",
    "frame-ancestors 'none'",
  ].join('; ');
}

/** Serves the built React app from webDir. Unknown paths fall back to index.html; nothing outside webDir is served. */
function registerAppProtocol() {
  const root = path.resolve(paths.webDir);
  protocol.handle('app', async (request) => {
    const url = new URL(request.url);
    let rel = decodeURIComponent(url.pathname);
    if (rel === '/' || rel === '') rel = '/index.html';
    let file = path.resolve(root, `.${rel}`);
    if (!file.startsWith(root + path.sep)) return new Response('Forbidden', { status: 403 });
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(root, 'index.html');
    const res = await net.fetch(pathToFileURL(file).toString());
    const headers = new Headers(res.headers);
    headers.set('Content-Security-Policy', csp());
    headers.set('X-Content-Type-Options', 'nosniff');
    return new Response(res.body, { status: res.status, headers });
  });
}

function isTrustedUrl(url) {
  return url.startsWith(`${APP_ORIGIN}/`) || url.startsWith('file:') || (paths.devUrl && url.startsWith(paths.devUrl));
}

/** No new windows, no navigation away from the app; external links open in the default browser. */
function hardenWebContents() {
  app.on('web-contents-created', (_e, contents) => {
    contents.setWindowOpenHandler(({ url }) => {
      if (/^https?:\/\//.test(url)) shell.openExternal(url);
      return { action: 'deny' };
    });
    contents.on('will-navigate', (event, url) => {
      if (!isTrustedUrl(url)) {
        event.preventDefault();
        if (/^https?:\/\//.test(url)) shell.openExternal(url);
      }
    });
    contents.on('will-attach-webview', (event) => event.preventDefault());
  });
}

const APP_ICON = path.join(__dirname, '..', 'build-resources', 'icon.png');

const webPreferences = {
  preload: path.join(__dirname, 'preload.js'),
  contextIsolation: true,
  nodeIntegration: false,
  sandbox: true,
  spellcheck: false,
};

// ------------------------------------------------------------------------------------------- windows

function createSplash() {
  splash = new BrowserWindow({
    width: 520, height: 420, resizable: false, frame: false, show: false, backgroundColor: '#0f1115',
    title: 'PKOS', icon: APP_ICON, webPreferences,
  });
  splash.loadFile(path.join(__dirname, 'splash', 'splash.html'));
  splash.once('ready-to-show', () => splash.show());
  splash.on('closed', () => { splash = null; });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1400, height: 900, minWidth: 960, minHeight: 640, show: false, backgroundColor: '#0f1115',
    title: 'PKOS', autoHideMenuBar: true, icon: APP_ICON, webPreferences,
  });
  mainWindow.loadURL(paths.devUrl || `${APP_ORIGIN}/index.html`);
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    if (splash) splash.close();
    // Dev aid: PKOS_SCREENSHOT=1 saves what the window shows to logs/main-window.png.
    if (process.env.PKOS_SCREENSHOT) {
      setTimeout(async () => {
        if (!mainWindow) return;
        const image = await mainWindow.webContents.capturePage();
        fs.writeFileSync(path.join(paths.logs, 'main-window.png'), image.toPNG());
        desktopLog.write('[pkos] screenshot saved\n');
      }, 4000);
    }
  });
  const wc = mainWindow.webContents;
  wc.on('did-finish-load', () => desktopLog.write(`[pkos] page loaded: ${wc.getURL()}\n`));
  wc.on('did-fail-load', (_e, code, desc, url) => desktopLog.write(`[pkos] page failed: ${code} ${desc} ${url}\n`));
  wc.on('console-message', (event) => {
    if (event.level === 'error' || event.level === 'warning') desktopLog.write(`[renderer ${event.level}] ${event.message}\n`);
  });
  wc.on('render-process-gone', (_e, details) => desktopLog.write(`[pkos] renderer gone: ${details.reason}\n`));
  mainWindow.on('closed', () => { mainWindow = null; });
}

function broadcast(channel, payload) {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) win.webContents.send(channel, payload);
  }
}

// ------------------------------------------------------------------------------------------- IPC

function fromOurWindow(event) {
  const url = event.senderFrame ? event.senderFrame.url : '';
  return isTrustedUrl(url);
}

function registerIpc() {
  ipcMain.on('pkos:get-config', (event) => {
    event.returnValue = fromOurWindow(event) ? {
      apiBase: supervisor ? supervisor.backend.url : null,
      version: app.getVersion(),
      dataDir: paths.dataDir,
      isDev,
    } : null;
  });
  const handle = (channel, fn) => ipcMain.handle(channel, (event, ...args) => (fromOurWindow(event) ? fn(...args) : null));
  handle('pkos:get-status', () => (supervisor ? supervisor.snapshot() : null));
  handle('pkos:open-logs', () => shell.openPath(paths.logs));
  handle('pkos:open-data', () => shell.openPath(paths.dataDir));
  handle('pkos:retry', () => startServices());
  handle('pkos:restart-services', async () => {
    await supervisor.restartAll();
    return supervisor.snapshot();
  });
  handle('pkos:quit', () => app.quit());

  // ---- backups (whole vault: every PKOS user on this computer)
  handle('pkos:backup-list', () => backups.list().map(({ path: _p, ...b }) => b));
  handle('pkos:backup-open-folder', () => {
    fs.mkdirSync(paths.backups, { recursive: true });
    return shell.openPath(paths.backups);
  });
  handle('pkos:backup-create', async (kind) => {
    const b = await backups.create(kind === 'before-import' ? 'before-import' : 'manual');
    desktopLog.write(`[pkos] backup created: ${b.name} (${b.size} bytes)\n`);
    const { path: _p, ...pub } = b;
    return pub;
  });
  handle('pkos:backup-restore', async (name) => {
    const win = BrowserWindow.getFocusedWindow() || mainWindow;
    let file = name ? path.join(paths.backups, path.basename(name)) : null;
    if (!file) {
      const pick = await dialog.showOpenDialog(win, {
        title: 'Restore PKOS backup', defaultPath: paths.backups, properties: ['openFile'],
        filters: [{ name: 'PKOS backup', extensions: ['dump'] }],
      });
      if (pick.canceled || !pick.filePaths[0]) return { canceled: true };
      file = pick.filePaths[0];
    }
    // Dev-only test hook: automated UI tests cannot click a native dialog. Ignored in the packaged app.
    const autoConfirm = isDev && !app.isPackaged && process.env.PKOS_TEST_AUTOCONFIRM === '1';
    const answer = autoConfirm ? { response: 0 } : await dialog.showMessageBox(win, {
      type: 'warning', buttons: ['Restore', 'Cancel'], defaultId: 1, cancelId: 1, noLink: true,
      title: 'Restore backup',
      message: `Replace all PKOS data with ${path.basename(file)}?`,
      detail: 'Every account, document and knowledge map on this computer is replaced by the backup. '
        + 'A backup of the current data is made first, so this can be undone.',
    });
    if (answer.response !== 0) return { canceled: true };
    desktopLog.write(`[pkos] restoring ${path.basename(file)}\n`);
    const result = await backups.restore(file, {
      stopBackend: () => supervisor.stopBackend(),
      startBackend: () => supervisor.startBackend(),
    });
    desktopLog.write(`[pkos] restore finished: ${JSON.stringify(result)}\n`);
    // Reload so the UI starts from the restored data (the login may no longer exist).
    setTimeout(() => { if (mainWindow) mainWindow.webContents.reload(); }, 300);
    return result;
  });

  // ---- diagnostics
  handle('pkos:copy-diagnostics', () => {
    const text = collectDiagnostics({
      appVersion: app.getVersion(), electronVersion: process.versions.electron, paths,
      snapshot: supervisor ? supervisor.snapshot() : null,
    });
    clipboard.writeText(text);
    return { copied: true, characters: text.length };
  });
}

// ------------------------------------------------------------------------------------------- lifecycle

async function startServices() {
  try {
    await supervisor.startAll();
    try {
      updateConfig(paths.configFile, { lastVersion: app.getVersion() });
    } catch (e) {
      desktopLog.write(`[pkos] could not record the app version: ${e.message}\n`);
    }
    if (!mainWindow) createMainWindow();
  } catch (e) {
    supervisor.fatal = e.message;
    broadcast('pkos:status', supervisor.snapshot());
  }
}

async function boot() {
  desktopLog = openLog(paths.logs, 'desktop');
  desktopLog.write(`[pkos] version ${app.getVersion()} electron ${process.versions.electron} dev=${isDev} data=${paths.dataDir}\n`);
  registerAppProtocol();
  hardenWebContents();
  registerIpc();
  createSplash();

  let cfg;
  try {
    cfg = loadOrCreateConfig(paths.configFile, safeStorage);
  } catch (e) {
    dialog.showErrorBox('PKOS cannot start', e.message);
    app.exit(1);
    return;
  }

  const origins = [APP_ORIGIN];
  if (paths.devUrl) origins.push(new URL(paths.devUrl).origin);
  const version = app.getVersion();
  let upgradeBackupPending = isUpgrade(cfg, version);
  supervisor = new Supervisor({
    paths, cfg, origins,
    // An update may bring migrations: back up the vault after the database is up and before the engine starts.
    beforeStart: async (name) => {
      if (name !== 'backend' || !upgradeBackupPending) return;
      upgradeBackupPending = false;
      try {
        const b = await backups.create('before-update');
        desktopLog.write(`[pkos] backup before update ${cfg.lastVersion || '(unknown)'} -> ${version}: ${b.name}\n`);
      } catch (e) {
        desktopLog.write(`[pkos] WARNING: backup before update failed: ${e.message}\n`);
      }
    },
  });
  backups = new BackupManager({
    pgBin: paths.pgBin, backupsDir: paths.backups, log: desktopLog,
    getConn: () => ({ port: supervisor.postgres.port, user: cfg.dbUser, password: cfg.dbPassword, db: cfg.dbName }),
  });
  supervisor.on('status', (s) => {
    broadcast('pkos:status', s);
    const line = Object.entries(s.services).map(([k, v]) => `${k}=${v.status}${v.detail ? ` (${v.detail})` : ''}`).join(' ');
    desktopLog.write(`[status] ${line}${s.apiBase ? ` api=${s.apiBase}` : ''}${s.fatal ? ` FATAL: ${s.fatal}` : ''}\n`);
  });
  await startServices();
}

app.on('before-quit', (event) => {
  if (quitting || !supervisor) return;
  event.preventDefault();
  quitting = true;
  for (const win of BrowserWindow.getAllWindows()) win.hide();
  supervisor.stopAll().finally(() => app.exit(0));
});

app.on('window-all-closed', () => app.quit());

'use strict';
// Bridge between the sandboxed pages (splash, React UI) and the main process. Only these calls are exposed.
const { contextBridge, ipcRenderer } = require('electron');

const cfg = ipcRenderer.sendSync('pkos:get-config') || {};

contextBridge.exposeInMainWorld('pkos', {
  isDesktop: true,
  apiBase: cfg.apiBase,
  version: cfg.version,
  dataDir: cfg.dataDir,
  isDev: cfg.isDev,
  getStatus: () => ipcRenderer.invoke('pkos:get-status'),
  onStatus: (callback) => {
    const handler = (_event, status) => callback(status);
    ipcRenderer.on('pkos:status', handler);
    return () => ipcRenderer.removeListener('pkos:status', handler);
  },
  openLogs: () => ipcRenderer.invoke('pkos:open-logs'),
  openDataFolder: () => ipcRenderer.invoke('pkos:open-data'),
  retry: () => ipcRenderer.invoke('pkos:retry'),
  restartServices: () => ipcRenderer.invoke('pkos:restart-services'),
  quit: () => ipcRenderer.invoke('pkos:quit'),
  backups: {
    list: () => ipcRenderer.invoke('pkos:backup-list'),
    create: (kind) => ipcRenderer.invoke('pkos:backup-create', kind),
    restore: (name) => ipcRenderer.invoke('pkos:backup-restore', name),
    openFolder: () => ipcRenderer.invoke('pkos:backup-open-folder'),
  },
  copyDiagnostics: () => ipcRenderer.invoke('pkos:copy-diagnostics'),
});

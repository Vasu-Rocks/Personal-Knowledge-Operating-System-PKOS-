'use strict';
// Vault backups with the bundled pg_dump / pg_restore (custom format, compressed). Backups cover the whole database,
// i.e. every PKOS user on this computer, and live in <data>\backups.
const fs = require('fs');
const path = require('path');
const { run } = require('./process');

const AUTO_KEEP = 5; // per automatic kind; manual backups are never deleted automatically
const NAME = /^pkos-(\d{8}-\d{6})-([a-z-]+)\.dump$/;

function stamp(date = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${date.getFullYear()}${p(date.getMonth() + 1)}${p(date.getDate())}-${p(date.getHours())}${p(date.getMinutes())}${p(date.getSeconds())}`;
}

class BackupManager {
  /**
   * @param pgBin folder with pg_dump.exe etc.
   * @param backupsDir where .dump files go
   * @param getConn () => { port, user, password, db } of the running database
   * @param runner injectable for tests (same contract as process.run)
   */
  constructor({ pgBin, backupsDir, getConn, log = { write() {} }, runner = run }) {
    Object.assign(this, { pgBin, backupsDir, getConn, log, runner });
    this.busy = false;
  }

  bin(exe) {
    return path.join(this.pgBin, process.platform === 'win32' ? `${exe}.exe` : exe);
  }

  env() {
    return { ...process.env, PGPASSWORD: this.getConn().password, PGCONNECT_TIMEOUT: '10' };
  }

  connArgs() {
    const c = this.getConn();
    return ['-h', '127.0.0.1', '-p', String(c.port), '-U', c.user];
  }

  list() {
    if (!fs.existsSync(this.backupsDir)) return [];
    return fs.readdirSync(this.backupsDir)
      .map((name) => {
        const m = NAME.exec(name);
        if (!m) return null;
        const file = path.join(this.backupsDir, name);
        const st = fs.statSync(file);
        return { name, path: file, kind: m[2], size: st.size, created: st.mtime.toISOString() };
      })
      .filter(Boolean)
      .sort((a, b) => b.name.localeCompare(a.name));
  }

  prune() {
    const byKind = {};
    for (const b of this.list()) {
      if (b.kind === 'manual') continue;
      (byKind[b.kind] = byKind[b.kind] || []).push(b);
    }
    for (const items of Object.values(byKind)) {
      for (const old of items.slice(AUTO_KEEP)) fs.rmSync(old.path, { force: true });
    }
  }

  async exclusive(fn) {
    if (this.busy) throw new Error('Another backup or restore is already running.');
    this.busy = true;
    try {
      return await fn();
    } finally {
      this.busy = false;
    }
  }

  /** kind: manual | before-update | before-restore | before-import */
  create(kind = 'manual') {
    return this.exclusive(() => this.createUnlocked(kind));
  }

  async createUnlocked(kind) {
    if (!/^[a-z-]+$/.test(kind)) throw new Error(`invalid backup kind ${kind}`);
    fs.mkdirSync(this.backupsDir, { recursive: true });
    const name = `pkos-${stamp()}-${kind}.dump`;
    const final = path.join(this.backupsDir, name);
    const tmp = `${final}.partial`;
    const r = await this.runner(this.bin('pg_dump'), [...this.connArgs(), '-d', this.getConn().db, '-Fc', '-Z', '6', '-f', tmp],
      { env: this.env(), log: this.log, timeoutMs: 30 * 60 * 1000 });
    if (r.code !== 0) {
      fs.rmSync(tmp, { force: true });
      throw new Error('The backup failed; see logs/desktop.log.');
    }
    fs.renameSync(tmp, final);
    this.prune();
    return this.list().find((b) => b.name === name);
  }

  /**
   * Replaces the database with a backup. Order of safety: verify the file, back up the current data, restore into a
   * temporary database, and only if that fully succeeds swap it in. If the engine then fails to start, swap back.
   */
  restore(file, { stopBackend, startBackend }) {
    return this.exclusive(async () => {
      if (!fs.existsSync(file)) throw new Error('Backup file not found.');
      const check = await this.runner(this.bin('pg_restore'), ['--list', file], { env: this.env(), log: null });
      if (check.code !== 0) throw new Error('This file is not a PKOS backup (pg_restore cannot read it).');

      const safety = await this.createUnlocked('before-restore');
      const { db } = this.getConn();
      const tmpDb = `${db}_restore`;
      const oldDb = `${db}_old_${stamp().replace('-', '_')}`;
      const psql = (sql) => this.runner(this.bin('psql'), [...this.connArgs(), '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', sql],
        { env: this.env(), log: this.log });

      await psql(`DROP DATABASE IF EXISTS "${tmpDb}"`);
      if ((await psql(`CREATE DATABASE "${tmpDb}"`)).code !== 0) throw new Error('Could not prepare the restore.');
      const r = await this.runner(this.bin('pg_restore'),
        [...this.connArgs(), '-d', tmpDb, '--no-owner', '--exit-on-error', file],
        { env: this.env(), log: this.log, timeoutMs: 60 * 60 * 1000 });
      if (r.code !== 0) {
        await psql(`DROP DATABASE IF EXISTS "${tmpDb}"`);
        throw new Error('The backup could not be restored; your data was not changed.');
      }

      await stopBackend();
      try {
        await psql(`SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${db}' AND pid <> pg_backend_pid()`);
        if ((await psql(`ALTER DATABASE "${db}" RENAME TO "${oldDb}"`)).code !== 0) throw new Error('rename current');
        if ((await psql(`ALTER DATABASE "${tmpDb}" RENAME TO "${db}"`)).code !== 0) {
          await psql(`ALTER DATABASE "${oldDb}" RENAME TO "${db}"`);
          throw new Error('rename restored');
        }
      } catch (e) {
        this.log.write(`[pkos] restore swap failed: ${e.message}\n`);
        await startBackend();
        throw new Error('The backup could not be switched in; your data was not changed.');
      }

      try {
        await startBackend();
      } catch (e) {
        this.log.write(`[pkos] engine failed on the restored database, rolling back: ${e.message}\n`);
        await stopBackend();
        await psql(`ALTER DATABASE "${db}" RENAME TO "${tmpDb}"`);
        await psql(`ALTER DATABASE "${oldDb}" RENAME TO "${db}"`);
        await psql(`DROP DATABASE IF EXISTS "${tmpDb}"`);
        await startBackend();
        throw new Error('PKOS could not start with that backup, so your previous data was put back.');
      }
      await psql(`DROP DATABASE IF EXISTS "${oldDb}"`);
      return { restored: path.basename(file), safetyBackup: safety.name };
    });
  }
}

module.exports = { BackupManager, stamp, AUTO_KEEP };

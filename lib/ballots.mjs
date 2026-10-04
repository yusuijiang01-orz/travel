import { mkdir, readFile, open, rename, unlink, rmdir, stat } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';

export const candidates = ['parrot', 'peixie', 'dongshan', 'shiluogu', 'fengcheng'];
const directory = resolve(process.env.DATA_DIR || './data');
const filename = join(directory, 'ballots.json');
const lock = join(directory, '.write-lock');
const pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
let queue = Promise.resolve();

export class PublicError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function validateBallot(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new PublicError(400, '请填写昵称并选择目的地。');
  }
  if (typeof value.nickname !== 'string' || value.nickname.length > 80) {
    throw new PublicError(400, '昵称格式不正确。');
  }
  const nickname = value.nickname.normalize('NFKC').trim().replace(/\s+/gu, '').toLowerCase();
  if ([...nickname].length < 2 || [...nickname].length > 16 || !/^[\p{L}\p{N}_.-]+$/u.test(nickname)) {
    throw new PublicError(400, '昵称需为 2–16 个中文、字母、数字或 _ . -，空格不计。');
  }
  const ids = value.candidates;
  if (!Array.isArray(ids) || ids.length < 1 || ids.length > 3 || new Set(ids).size !== ids.length ||
      ids.some(id => typeof id !== 'string' || !candidates.includes(id))) {
    throw new PublicError(400, '请选择 1–3 个不同目的地。');
  }
  if (value.mode !== 'single' && value.mode !== 'multiple') throw new PublicError(400, '请选择投票方式。');
  if (value.mode === 'single' && ids.length !== 1) throw new PublicError(400, '单选只能选择一个目的地。');
  return { nicknameHash: createHash('sha256').update(nickname).digest('hex'), candidates: ids, mode: value.mode };
}

async function readBallots() {
  try {
    const data = JSON.parse(await readFile(filename, 'utf8'));
    if (data.version !== 1 || !Array.isArray(data.ballots) || data.ballots.length > 10000 ||
        data.ballots.some(item => !/^[a-f0-9]{64}$/.test(item.nicknameHash) || !Array.isArray(item.candidates) ||
          item.candidates.length < 1 || item.candidates.length > 3 ||
          new Set(item.candidates).size !== item.candidates.length || item.candidates.some(id => !candidates.includes(id)))) {
      throw new Error('Invalid ballot store');
    }
    return data.ballots;
  } catch (error) {
    if (error.code === 'ENOENT') return [];
    throw error; // Never reset a corrupt store and lose existing votes.
  }
}

async function acquireLock() {
  await mkdir(directory, { recursive: true, mode: 0o700 });
  for (let attempt = 0; attempt < 40; attempt++) {
    try { await mkdir(lock, { mode: 0o700 }); return; }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      // Recover an empty lock left by an interrupted write after its 30 second lease.
      const metadata = await stat(lock).catch(() => null);
      if (metadata && Date.now() - metadata.mtimeMs > 30000) {
        await rmdir(lock).catch(() => {});
      }
      await pause(50);
    }
  }
  throw new PublicError(503, '投票服务正忙，请稍后重试。');
}

async function save(ballots) {
  const temporary = join(directory, `.ballots-${randomUUID()}.tmp`);
  let handle;
  try {
    handle = await open(temporary, 'wx', 0o600);
    await handle.writeFile(JSON.stringify({ version: 1, ballots }), 'utf8');
    await handle.sync();
    await handle.close(); handle = null;
    await rename(temporary, filename);
    // Persist the rename itself on Linux. Windows does not support opening directories.
    if (process.platform !== 'win32') {
      const parent = await open(directory, 'r');
      try { await parent.sync(); } finally { await parent.close(); }
    }
  } finally {
    await handle?.close();
    await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') console.error('Temporary file cleanup failed'); });
  }
}

function summarize(ballots) {
  const totals = Object.fromEntries(candidates.map(id => [id, 0]));
  for (const ballot of ballots) for (const id of ballot.candidates) totals[id]++;
  return { voters: ballots.length, selections: Object.values(totals).reduce((sum, value) => sum + value, 0),
    totals, updatedAt: new Date().toISOString(), rule: 'one-final-ballot-per-normalized-nickname' };
}

export async function getResults() { return summarize(await readBallots()); }

export function submitBallot(ballot) {
  const operation = queue.then(async () => {
    await acquireLock();
    try {
      const ballots = await readBallots();
      if (ballots.some(previous => previous.nicknameHash === ballot.nicknameHash)) {
        throw new PublicError(409, '这个昵称已提交过。每个昵称只能投一次，提交后不能修改。');
      }
      if (ballots.length >= 10000) throw new PublicError(503, '本次投票已停止收集。');
      ballots.push({ ...ballot, submittedAt: new Date().toISOString() });
      await save(ballots);
      return summarize(ballots);
    } finally { await rmdir(lock); }
  });
  queue = operation.catch(() => {});
  return operation;
}

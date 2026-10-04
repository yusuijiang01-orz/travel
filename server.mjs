import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { PublicError, getResults, submitBallot, validateBallot } from './lib/ballots.mjs';

const root = fileURLToPath(new URL('./public/', import.meta.url));
const port = Number(process.env.PORT || 3000);
const basePath = (process.env.BASE_PATH || '').replace(/\/+$/, '');
if (basePath && !/^\/(?:[a-zA-Z0-9_-]+\/)*[a-zA-Z0-9_-]+$/.test(basePath)) {
  throw new Error('BASE_PATH must be empty or a path such as /family-trip.');
}
const originUrl = new URL(process.env.PUBLIC_ORIGIN || `http://localhost:${port}`);
if (!['http:', 'https:'].includes(originUrl.protocol) || originUrl.username || originUrl.password ||
    originUrl.pathname !== '/' || originUrl.search || originUrl.hash) {
  throw new Error('PUBLIC_ORIGIN must contain only the public scheme and host; put the path in BASE_PATH.');
}
const allowedOrigin = originUrl.origin;
const rates = new Map();
const files = new Map([
  ['/', ['index.html', 'text/html; charset=utf-8']],
  ['/styles.css', ['styles.css', 'text/css; charset=utf-8']],
  ['/app.js', ['app.js', 'text/javascript; charset=utf-8']],
  ['/destinations.js', ['destinations.js', 'text/javascript; charset=utf-8']],
  ['/favicon.svg', ['favicon.svg', 'image/svg+xml']]
]);
const securityHeaders = {
  'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' https://ly.fjsen.com https://img.lyzhly.com https://wlt.fujian.gov.cn https://csglj.longyan.gov.cn https://www.fujian.gov.cn; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
};

function json(response, status, body, extra = {}) {
  response.writeHead(status, { ...securityHeaders, 'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store', ...extra });
  response.end(JSON.stringify(body));
}

function rateLimit(request, write) {
  // Enable TRUST_PROXY only behind the private network or loopback proxy binding.
  const address = process.env.TRUST_PROXY === '1'
    ? String(request.headers['x-forwarded-for'] || request.socket.remoteAddress).split(',').at(-1).trim()
    : request.socket.remoteAddress;
  const key = `${write ? 'write' : 'read'}:${address}`;
  const now = Date.now();
  let record = rates.get(key);
  if (!record || now >= record.until) record = { count: 0, until: now + 60000 };
  if (!rates.has(key) && rates.size >= 20000) throw new PublicError(503, '服务繁忙，请稍后再来。');
  record.count++; rates.set(key, record);
  if (record.count > (write ? 8 : 90)) throw new PublicError(429, '操作太频繁，请一分钟后重试。');
}
const cleanup = setInterval(() => {
  for (const [key, record] of rates) if (Date.now() >= record.until) rates.delete(key);
}, 60000);
cleanup.unref();

async function body(request) {
  if (!/^application\/json(?:\s*;|$)/i.test(request.headers['content-type'] || '')) {
    throw new PublicError(415, '请使用 JSON 格式提交。');
  }
  if (Number(request.headers['content-length'] || 0) > 2048) throw new PublicError(413, '提交内容太长。');
  const parts = []; let bytes = 0;
  for await (const chunk of request) {
    bytes += chunk.length;
    if (bytes > 2048) throw new PublicError(413, '提交内容太长。');
    parts.push(chunk);
  }
  try { return JSON.parse(Buffer.concat(parts).toString('utf8')); }
  catch { throw new PublicError(400, '提交内容无法读取，请重新填写。'); }
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, allowedOrigin);
    if (basePath && url.pathname === basePath) {
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        return json(response, 405, { error: '请使用带斜杠的页面地址。' }, { Allow: 'GET, HEAD' });
      }
      response.writeHead(308, { ...securityHeaders, Location: `${basePath}/${url.search}`, 'Cache-Control': 'no-cache' });
      return response.end();
    }
    if (basePath && !url.pathname.startsWith(`${basePath}/`)) {
      return json(response, 404, { error: '页面未找到。' });
    }
    const pathname = basePath ? url.pathname.slice(basePath.length) : url.pathname;
    if (pathname.startsWith('/api/')) {
      rateLimit(request, request.method === 'POST');
      if (pathname === '/api/health' && request.method === 'GET') {
        await getResults(); return json(response, 200, { status: 'ok' });
      }
      if (pathname === '/api/results' && request.method === 'GET') return json(response, 200, await getResults());
      if (pathname === '/api/votes' && request.method === 'POST') {
        const origin = request.headers.origin;
        if ((origin && origin !== allowedOrigin) || request.headers['sec-fetch-site'] === 'cross-site') {
          throw new PublicError(403, '请从旅行网站内提交投票。');
        }
        const ballot = validateBallot(await body(request));
        return json(response, 201, { message: '你的选择已收好，出发前一起决定。', results: await submitBallot(ballot) });
      }
      return json(response, 404, { error: '没有这个接口。' });
    }
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return json(response, 405, { error: '此页面只支持浏览。' }, { Allow: 'GET, HEAD' });
    }
    const file = files.get(pathname);
    if (!file) return json(response, 404, { error: '页面未找到。' });
    const saved = await readFile(resolve(root, file[0]));
    const content = file[0] === 'index.html'
      ? Buffer.from(saved.toString('utf8').replaceAll('__BASE_PATH__', basePath)) : saved;
    response.writeHead(200, { ...securityHeaders, 'Content-Type': file[1],
      'Content-Length': content.length, 'Cache-Control': 'no-cache' });
    response.end(request.method === 'HEAD' ? undefined : content);
  } catch (error) {
    if (response.headersSent || response.destroyed) return;
    if (!(error instanceof PublicError)) console.error('Request failed:', error.code || error.name);
    json(response, error instanceof PublicError ? error.status : 503,
      { error: error instanceof PublicError ? error.message : '服务暂时不可用，请稍后重试。' },
      error.status === 429 ? { 'Retry-After': '60' } : {});
  }
});
server.requestTimeout = 10000;
server.headersTimeout = 10000;
server.maxHeadersCount = 40;
server.listen(port, process.env.HOST || '127.0.0.1', () => console.log(`Travel guide: ${allowedOrigin}${basePath}/`));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(0), 12000).unref();
});

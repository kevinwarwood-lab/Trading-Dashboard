const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');
const url   = require('url');

const PORT = process.env.PORT || 4200;
const DIR  = __dirname;

// Only proxy PEAD (no CORS) and TV (localhost only)
// ES has Access-Control-Allow-Origin: * so the browser calls it directly
const UPSTREAMS = {
  '/proxy/pead/' : 'https://pead-strategy-production.up.railway.app',
  '/proxy/tv/'   : process.env.TV_BASE_URL || 'http://localhost:3101',
};

// Prevent unhandled errors from crashing the process
process.on('uncaughtException',  err => console.error('[uncaughtException]',  err.message));
process.on('unhandledRejection', err => console.error('[unhandledRejection]', err));

function proxyRequest(targetUrl, res) {
  const lib = targetUrl.startsWith('https') ? https : http;
  console.log(`[proxy] → ${targetUrl}`);

  const req = lib.get(targetUrl, { headers: { 'Accept': 'application/json' } }, upstream => {
    console.log(`[proxy] ← ${upstream.statusCode} ${targetUrl}`);
    // Collect body before piping so we can send proper error on failure
    const chunks = [];
    upstream.on('data', c => chunks.push(c));
    upstream.on('end', () => {
      const body = Buffer.concat(chunks);
      res.writeHead(upstream.statusCode, {
        'Content-Type': upstream.headers['content-type'] || 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Cache-Control': 'no-store',
      });
      res.end(body);
    });
    upstream.on('error', err => {
      console.error(`[proxy] stream error ${targetUrl}: ${err.message}`);
      if (!res.headersSent) {
        res.writeHead(502);
        res.end(JSON.stringify({ error: err.message }));
      }
    });
  });

  req.on('error', err => {
    console.error(`[proxy] request error ${targetUrl}: ${err.message}`);
    if (!res.headersSent) {
      res.writeHead(502);
      res.end(JSON.stringify({ error: err.message }));
    }
  });

  req.setTimeout(10000, () => {
    console.error(`[proxy] timeout ${targetUrl}`);
    req.destroy();
    if (!res.headersSent) {
      res.writeHead(504);
      res.end(JSON.stringify({ error: 'upstream timeout' }));
    }
  });
}

const MIME = { '.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.json':'application/json' };

const server = http.createServer((req, res) => {
  let pathname;
  try { pathname = url.parse(req.url).pathname; }
  catch { pathname = '/'; }

  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET' });
    res.end(); return;
  }

  // Proxy routes
  for (const [prefix, base] of Object.entries(UPSTREAMS)) {
    if (pathname.startsWith(prefix)) {
      const rest = pathname.slice(prefix.length - 1);
      const qs   = url.parse(req.url).search || '';
      proxyRequest(base + rest + qs, res);
      return;
    }
  }

  // Static files
  const filePath = path.join(DIR, pathname === '/' ? 'dashboard.html' : pathname);
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    const ext = path.extname(filePath);
    res.writeHead(200, {
      'Content-Type': MIME[ext] || 'text/plain',
      'Cache-Control': 'no-store',
    });
    res.end(data);
  });
});

server.on('error', err => console.error('[server error]', err.message));
server.listen(PORT, '0.0.0.0', () => console.log(`Dashboard → http://0.0.0.0:${PORT}/`));

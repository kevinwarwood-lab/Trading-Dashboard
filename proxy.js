const http  = require('http');
const https = require('https');
const fs    = require('fs');
const path  = require('path');
const url   = require('url');

const PORT = process.env.PORT || 4200;
const DIR  = __dirname;

const UPSTREAMS = {
  '/proxy/es/'   : 'https://es-agents-production.up.railway.app',
  '/proxy/pead/' : 'https://pead-strategy-production.up.railway.app',
  '/proxy/tv/'   : process.env.TV_BASE_URL || 'http://localhost:3101',
};

function proxyRequest(targetUrl, res) {
  const lib = targetUrl.startsWith('https') ? https : http;
  lib.get(targetUrl, { headers: { 'Accept': 'application/json' } }, upstream => {
    res.writeHead(upstream.statusCode, {
      'Content-Type': upstream.headers['content-type'] || 'application/json',
      'Access-Control-Allow-Origin': '*',
    });
    upstream.pipe(res);
  }).on('error', err => {
    res.writeHead(502);
    res.end(JSON.stringify({ error: err.message }));
  });
}

const MIME = { '.html':'text/html','.js':'application/javascript','.css':'text/css','.json':'application/json' };

const server = http.createServer((req, res) => {
  const parsed = url.parse(req.url);
  const pathname = parsed.pathname;

  // CORS preflight
  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET' });
    res.end(); return;
  }

  // Proxy routes
  for (const [prefix, base] of Object.entries(UPSTREAMS)) {
    if (pathname.startsWith(prefix)) {
      const rest = pathname.slice(prefix.length - 1); // keep leading slash
      const qs   = parsed.search || '';
      proxyRequest(base + rest + qs, res);
      return;
    }
  }

  // Static files
  let filePath = path.join(DIR, pathname === '/' ? 'dashboard.html' : pathname);
  fs.readFile(filePath, (err, data) => {
    if (err) { res.writeHead(404); res.end('Not found'); return; }
    const ext = path.extname(filePath);
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'text/plain' });
    res.end(data);
  });
});

server.listen(PORT, () => console.log(`Dashboard → http://localhost:${PORT}/`));

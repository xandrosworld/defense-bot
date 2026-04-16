# ============================================================
#  Defense Bot – server.py
#  Keys đọc từ env vars (local: .env file, production: Railway)
#  Routes:
#    POST /api/chat   → proxy gọi LLM (GPT hoặc Claude)
#    POST /api/log    → append Q&A vào chat_log.json
#    GET  /api/log    → trả về toàn bộ log
#    GET  /api/export → download chat_log.json
#    DELETE /api/log  → xóa log
#    GET  /*          → serve static files (index.html, app.js, style.css)
# ============================================================

import json, os, datetime, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError

# ── Load .env file nếu chạy local ────────────────────────────
def load_dotenv():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
    if not os.path.exists(env_path):
        return
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_dotenv()

# ── Config ────────────────────────────────────────────────────
PORT     = int(os.environ.get('PORT', 3000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'chat_log.json')

OPENAI_API_KEY    = os.environ.get('OPENAI_API_KEY', '')
CLAUDIBLE_API_KEY = os.environ.get('CLAUDIBLE_API_KEY', '')

BOTS = {
    'gpt': {
        'name':    'ChatGPT',
        'model':   'gpt-4o',
        'url':     'https://api.openai.com/v1/chat/completions',
        'key_var': 'OPENAI_API_KEY',
    },
    'claude': {
        'name':    'Claude',
        'model':   'claude-sonnet-4.6',
        'url':     'https://claudible.io/v1/chat/completions',
        'key_var': 'CLAUDIBLE_API_KEY',
    },
}

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css':  'text/css; charset=utf-8',
    '.js':   'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.ico':  'image/x-icon',
}

# ── Log helpers ───────────────────────────────────────────────
def read_log():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def write_log(data):
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ── HTTP Handler ──────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  [{datetime.datetime.now().strftime('%H:%M:%S')}] {self.command} {self.path}")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_cors(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def read_body(self):
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length)
        return json.loads(raw)

    # OPTIONS
    def do_OPTIONS(self):
        self.send_cors()

    # ── GET ───────────────────────────────────────────────────
    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/api/log':
            self.send_json(200, read_log())
            return

        if path == '/api/export':
            log  = read_log()
            body = json.dumps(log, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', 'attachment; filename="chat_log.json"')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
            return

        # Static files
        if path in ('/', ''):
            path = '/index.html'
        file_path = os.path.join(BASE_DIR, path.lstrip('/'))
        if os.path.isfile(file_path):
            ext  = os.path.splitext(file_path)[1].lower()
            mime = MIME.get(ext, 'application/octet-stream')
            with open(file_path, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_json(404, {'error': 'Not found'})

    # ── POST ──────────────────────────────────────────────────
    def do_POST(self):
        path = urlparse(self.path).path

        # ── /api/chat → LLM proxy ─────────────────────────────
        if path == '/api/chat':
            try:
                data     = self.read_body()
                bot_key  = data.get('bot', 'gpt')
                messages = data.get('messages', [])  # includes system message

                bot = BOTS.get(bot_key)
                if not bot:
                    self.send_json(400, {'error': f'Unknown bot: {bot_key}'})
                    return

                api_key = os.environ.get(bot['key_var'], '')
                if not api_key:
                    self.send_json(500, {'error': f'{bot["key_var"]} not configured on server'})
                    return

                payload = json.dumps({
                    'model':       bot['model'],
                    'messages':    messages,
                    'temperature': 0.3,
                    'max_tokens':  800,
                }).encode('utf-8')

                req = Request(
                    bot['url'],
                    data=payload,
                    headers={
                        'Content-Type':  'application/json',
                        'Authorization': f'Bearer {api_key}',
                        # Cloudflare bypass headers
                        'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        'Accept':          'application/json, text/plain, */*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Origin':          'https://claudible.io',
                        'Referer':         'https://claudible.io/',
                    },
                    method='POST'
                )

                try:
                    with urlopen(req, timeout=30) as resp:
                        result = json.loads(resp.read().decode('utf-8'))
                except HTTPError as e:
                    err_body = e.read().decode('utf-8')
                    try:
                        err_json = json.loads(err_body)
                        msg = err_json.get('error', {}).get('message', str(e))
                    except Exception:
                        msg = err_body or str(e)
                    self.send_json(e.code, {'error': msg})
                    return

                reply = result.get('choices', [{}])[0].get('message', {}).get('content', '')
                self.send_json(200, {'reply': reply, 'bot': bot['name'], 'model': bot['model']})

            except Exception as e:
                self.send_json(500, {'error': str(e)})
            return

        # ── /api/log → save Q&A ───────────────────────────────
        if path == '/api/log':
            try:
                data = self.read_body()
            except Exception:
                self.send_json(400, {'error': 'Invalid JSON'})
                return

            entry = {
                'id':        len(read_log()) + 1,
                'timestamp': data.get('timestamp', datetime.datetime.utcnow().isoformat()),
                'bot':       data.get('bot', 'unknown'),
                'model':     data.get('model', 'unknown'),
                'isAttack':  data.get('isAttack', False),
                'isBlocked': data.get('isBlocked', False),
                'user':      data.get('user', ''),
                'assistant': data.get('assistant', ''),
            }
            log = read_log()
            log.append(entry)
            write_log(log)
            preview = entry['user'][:60] + ('...' if len(entry['user']) > 60 else '')
            print(f"  [LOG] #{entry['id']} | {entry['bot']} | attack:{entry['isAttack']} | {preview}")
            self.send_json(200, {'ok': True, 'total': len(log)})
            return

        self.send_json(404, {'error': 'Not found'})

    # ── DELETE ────────────────────────────────────────────────
    def do_DELETE(self):
        if urlparse(self.path).path == '/api/log':
            write_log([])
            print('  [CLEAR] Log cleared')
            self.send_json(200, {'ok': True})
        else:
            self.send_json(404, {'error': 'Not found'})


# ── Start ─────────────────────────────────────────────────────
if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    missing = [k for k in ('OPENAI_API_KEY', 'CLAUDIBLE_API_KEY') if not os.environ.get(k)]
    if missing:
        print(f'  [WARN] Missing env vars: {", ".join(missing)}')
        print('         Create a .env file or set them in Railway.')

    host   = '0.0.0.0'
    server = HTTPServer((host, PORT), Handler)
    print(f'[Defense Bot] Listening on http://localhost:{PORT}')
    print(f'[Defense Bot] Log file: {LOG_FILE}')
    print('[Defense Bot] Press Ctrl+C to stop')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('[Defense Bot] Server stopped.')
        server.server_close()

// ============================================================
//  Defense Bot – Mini Express Server
//  - Serves the frontend (index.html, style.css, app.js)
//  - POST /api/log   → append a Q&A entry to chat_log.json
//  - GET  /api/log   → return the full log
//  - GET  /api/export → download chat_log.json
// ============================================================

const express = require('express');
const fs      = require('fs');
const path    = require('path');
const cors    = require('cors');

const app     = express();
const PORT    = 3000;
const LOG_FILE = path.join(__dirname, 'chat_log.json');

// ── Middleware ────────────────────────────────────────────────
app.use(cors());
app.use(express.json({ limit: '5mb' }));
app.use(express.static(__dirname)); // serve index.html, style.css, app.js

// ── Helpers ───────────────────────────────────────────────────
function readLog() {
  if (!fs.existsSync(LOG_FILE)) return [];
  try { return JSON.parse(fs.readFileSync(LOG_FILE, 'utf-8')); }
  catch { return []; }
}

function writeLog(data) {
  fs.writeFileSync(LOG_FILE, JSON.stringify(data, null, 2), 'utf-8');
}

// ── Routes ────────────────────────────────────────────────────

// Append one Q&A entry
// Body: { bot, model, role_user, content_user, role_bot, content_bot, isBlocked, timestamp }
app.post('/api/log', (req, res) => {
  try {
    const entry = {
      id:           Date.now(),
      timestamp:    req.body.timestamp || new Date().toISOString(),
      bot:          req.body.bot       || 'unknown',
      model:        req.body.model     || 'unknown',
      isAttack:     req.body.isAttack  || false,
      isBlocked:    req.body.isBlocked || false,
      user:         req.body.user      || '',
      assistant:    req.body.assistant || '',
    };

    const log = readLog();
    log.push(entry);
    writeLog(log);

    console.log(`[LOG] #${log.length} | ${entry.bot} | attack:${entry.isAttack} | ${entry.user.substring(0,60)}...`);
    res.json({ ok: true, total: log.length });
  } catch (err) {
    console.error('[LOG ERROR]', err.message);
    res.status(500).json({ ok: false, error: err.message });
  }
});

// Get full log as JSON
app.get('/api/log', (req, res) => {
  res.json(readLog());
});

// Download chat_log.json
app.get('/api/export', (req, res) => {
  if (!fs.existsSync(LOG_FILE)) {
    return res.status(404).json({ error: 'No log file yet.' });
  }
  res.download(LOG_FILE, 'chat_log.json');
});

// Clear log
app.delete('/api/log', (req, res) => {
  writeLog([]);
  res.json({ ok: true });
});

// ── Start ─────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log('');
  console.log('  🛡️  Defense Bot Server running!');
  console.log(`  ➜  Open browser: http://localhost:${PORT}`);
  console.log(`  ➜  Log file:     ${LOG_FILE}`);
  console.log('');
});

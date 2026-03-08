#!/usr/bin/env node
/**
 * render_card.js — Cinema-quality title card renderer using Node.js canvas
 *
 * Usage:
 *   node render_card.js --type title_card --config '{"lines":[...]}' --output out.png
 *   node render_card.js --type main_title --config '{"title":"PLUNGE","tagline":"..."}' --output out.png
 *
 * Options:
 *   --type    title_card | main_title
 *   --config  JSON config string (see YAML_REFERENCE.md)
 *   --output  Output PNG path
 *   --width   Frame width  (default: 1920)
 *   --height  Frame height (default: 1080)
 *
 * Fonts: auto-detected from repo fonts/ dir and common system paths.
 * Install deps: cd canvas_renderer && npm install
 */
const { createCanvas, registerFont } = require('canvas');
const path = require('path');
const fs   = require('fs');

// ── Font discovery (repo-local preferred, system fallback) ────────────────────
const SCRIPT_DIR = path.dirname(__filename);
const REPO_ROOT  = path.resolve(SCRIPT_DIR, '..');

function tryFont(p, family, opts) {
  if (fs.existsSync(p)) {
    try { registerFont(p, { family, ...opts }); return true; } catch(e) {}
  }
  return false;
}

// Bebas Neue — repo-bundled (fonts/BebasNeue.ttf)
tryFont(path.join(REPO_ROOT, 'fonts', 'BebasNeue.ttf'), 'BebasNeue') ||
tryFont('/usr/share/fonts/truetype/bebas-neue/BebasNeue-Regular.ttf', 'BebasNeue');

// NimbusSans — system
tryFont('/usr/share/fonts/opentype/urw-base35/NimbusSans-Bold.otf',    'NimbusSans', { weight: 'bold' });
tryFont('/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf', 'NimbusSansReg');

// ── Args ──────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
let type = 'title_card', configStr = '{}', outputPath = '/tmp/card.png', W = 1920, H = 1080;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--type')   type       = args[++i];
  if (args[i] === '--config') configStr  = args[++i];
  if (args[i] === '--output') outputPath = args[++i];
  if (args[i] === '--width')  W          = parseInt(args[++i]);
  if (args[i] === '--height') H          = parseInt(args[++i]);
}
const cfg = JSON.parse(configStr);

// ── Layout constants ──────────────────────────────────────────────────────────
const BAR_H    = Math.floor(H * 0.095);
const SAFE_T   = BAR_H;
const SAFE_B   = H - BAR_H;
const SAFE_MID = (SAFE_T + SAFE_B) / 2;
const MAX_W    = W * 0.84;
const GAP      = 12;

const COLORS = {
  white:  '#FFFFFF',
  gold:   '#D4AF37',
  goldhi: '#F5E080',
  grey:   '#9090A0',
  black:  '#000000',
  red:    '#C81E1E',
};

const canvas = createCanvas(W, H);
const ctx    = canvas.getContext('2d');

// ── Helpers ───────────────────────────────────────────────────────────────────
function fontStr(family, size) {
  if (family === 'bebas') return `${size}px BebasNeue, sans-serif`;
  return `bold ${size}px NimbusSans, sans-serif`;
}

function autofitSize(text, family, desiredSize, maxW) {
  let size = desiredSize;
  while (size > 18) {
    ctx.font = fontStr(family, size);
    if (ctx.measureText(text).width <= maxW) return size;
    size = Math.floor(size * 0.93);
  }
  return 18;
}

function drawGlow(text, x, y, color, glowColor, glowBlur) {
  ctx.save();
  ctx.shadowColor = glowColor;
  ctx.shadowBlur  = glowBlur;
  ctx.fillStyle   = glowColor;
  ctx.textAlign   = 'center';
  ctx.textBaseline = 'middle';
  for (let p = 0; p < 3; p++) ctx.fillText(text, x, y);
  ctx.restore();
}

function drawText(text, x, y, color) {
  ctx.save();
  ctx.fillStyle    = 'rgba(0,0,0,0.7)';
  ctx.textAlign    = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x + 2, y + 3);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
  ctx.restore();
}

function drawGoldRule(y) {
  ctx.save();
  ctx.strokeStyle = 'rgba(212,175,55,0.9)';
  ctx.lineWidth   = 2;
  ctx.shadowColor = 'rgba(212,175,55,0.6)';
  ctx.shadowBlur  = 8;
  const rx1 = W * 0.1, rx2 = W * 0.9;
  ctx.beginPath(); ctx.moveTo(rx1, y); ctx.lineTo(rx2, y); ctx.stroke();
  ctx.restore();
}

function drawBars() {
  ctx.fillStyle = '#000000';
  ctx.fillRect(0, 0, W, BAR_H);
  ctx.fillRect(0, H - BAR_H, W, BAR_H);
}

function drawVignette() {
  const cx = W / 2, cy = H / 2;
  const r  = Math.max(W, H) * 0.75;
  const g  = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r);
  g.addColorStop(0, 'rgba(0,0,0,0)');
  g.addColorStop(1, 'rgba(0,0,0,0.65)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W, H);
}

// ── Title Card ────────────────────────────────────────────────────────────────
function renderTitleCard() {
  // Background
  ctx.fillStyle = '#07071A';
  ctx.fillRect(0, 0, W, H);

  const lines = cfg.lines || [];
  if (!lines.length) { drawBars(); save(); return; }

  // Measure all lines
  const items = lines.map(ln => {
    const text   = String(ln.text || '');
    const family = ln.font === 'bebas' ? 'bebas' : 'sans';
    const size   = autofitSize(text, family, ln.size || 80, MAX_W);
    ctx.font     = fontStr(family, size);
    const w      = ctx.measureText(text).width;
    return { text, family, size, color: COLORS[ln.color] || '#FFFFFF', w };
  });

  // Approximate line heights
  const lineHeights = items.map(it => it.size * 0.85);
  const totalH      = lineHeights.reduce((a, b) => a + b, 0) + GAP * (items.length - 1);
  const blockTop    = SAFE_MID - totalH / 2;

  // Gold rules bracketing text block
  const RULE_PAD = 22;
  drawGoldRule(blockTop - RULE_PAD);
  drawGoldRule(blockTop + totalH + RULE_PAD);

  // Draw each line
  let cy = blockTop;
  items.forEach((it, idx) => {
    const lh   = lineHeights[idx];
    const midY = cy + lh / 2;
    const isGold  = it.color === COLORS.gold;
    const isLarge = it.size >= 150;
    ctx.font = fontStr(it.family, it.size);

    if (isGold) {
      drawGlow(it.text, W/2, midY, it.color, 'rgba(212,175,55,0.7)', 28);
    } else if (isLarge) {
      drawGlow(it.text, W/2, midY, it.color, 'rgba(230,230,255,0.4)', 24);
    }
    drawText(it.text, W/2, midY, it.color);
    cy += lh + GAP;
  });

  drawVignette();
  drawBars();
}

// ── Main Title ────────────────────────────────────────────────────────────────
function renderMainTitle() {
  const title   = cfg.title   || 'UNTITLED';
  const tagline = cfg.tagline || '';

  ctx.fillStyle = '#03030C';
  ctx.fillRect(0, 0, W, H);

  const MID = H / 2;
  const RULE_TOP = MID - 105;
  const RULE_BOT = MID + 100;
  const TITLE_Y  = (RULE_TOP + RULE_BOT) / 2 + 10;
  const THE_Y    = H * 0.29;

  // "SUMMER 2026" label
  ctx.font      = `52px NimbusSans, sans-serif`;
  ctx.fillStyle = COLORS.gold;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('SUMMER  2026', W / 2, H * 0.21);

  // Gold rules
  drawGoldRule(RULE_TOP);
  drawGoldRule(RULE_BOT);

  // "T H E" — above top rule
  ctx.font = `88px BebasNeue, sans-serif`;
  drawGlow('T H E', W/2, THE_Y, '#DDDDDD', 'rgba(200,200,255,0.35)', 18);
  drawText('T H E', W/2, THE_Y, '#DDDDDD');

  // Main title — big, glowing
  const titleSize = autofitSize(title, 'bebas', 290, W * 0.9);
  ctx.font = fontStr('bebas', titleSize);
  drawGlow(title, W/2, TITLE_Y, COLORS.white, 'rgba(220,220,255,0.5)', 35);
  drawText(title, W/2, TITLE_Y, COLORS.white);

  // Tagline
  if (tagline) {
    ctx.font      = `36px NimbusSans, sans-serif`;
    ctx.fillStyle = COLORS.grey;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(`"${tagline}"`, W/2, H * 0.75);
  }

  // Rating line
  ctx.font      = `22px NimbusSans, sans-serif`;
  ctx.fillStyle = 'rgba(100,100,130,0.8)';
  ctx.fillText('RATED PG-13  ·  SOME PLUNGING MAY BE INTENSE FOR YOUNG VIEWERS', W/2, H * 0.82);

  drawVignette();
  drawBars();
}

// ── Render & Save ─────────────────────────────────────────────────────────────
if (type === 'main_title') {
  renderMainTitle();
} else {
  renderTitleCard();
}

const buf = canvas.toBuffer('image/png');
fs.writeFileSync(outputPath, buf);

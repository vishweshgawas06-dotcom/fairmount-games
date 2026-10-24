import { POCKET_ORDER, pocketColor, resultFromSnapshot, targetAngle } from './wheel.mjs';

const $ = id => document.getElementById(id);
const SVG_NS = 'http://www.w3.org/2000/svg';
const state = { round: null, offset: 0, lastResultId: null, angle: 0 };
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

function svgElement(tag, attributes) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}
function point(radius, degrees) {
  const angle = degrees * Math.PI / 180;
  return [210 + radius * Math.cos(angle), 210 + radius * Math.sin(angle)];
}
function buildWheel() {
  const ring = $('pocket-ring');
  const step = 360 / POCKET_ORDER.length;
  POCKET_ORDER.forEach((number, index) => {
    const start = -90 + (index - .5) * step;
    const end = start + step;
    const [x1, y1] = point(188, start);
    const [x2, y2] = point(188, end);
    const [x3, y3] = point(114, end);
    const [x4, y4] = point(114, start);
    const colors = { red: '#922e36', black: '#111c1b', green: '#13764c' };
    const path = svgElement('path', {
      d: `M${x1} ${y1} A188 188 0 0 1 ${x2} ${y2} L${x3} ${y3} A114 114 0 0 0 ${x4} ${y4} Z`,
      fill: colors[pocketColor(number)], stroke: '#d8b77c', 'stroke-width': '.7',
    });
    ring.append(path);
    const [x, y] = point(153, -90 + index * step);
    const label = svgElement('text', { x, y, fill: '#fff9e9', 'text-anchor': 'middle',
      'dominant-baseline': 'middle', 'font-size': number > 9 ? 11 : 12,
      'font-family': 'Arial, sans-serif', 'font-weight': 'bold' });
    label.textContent = String(number);
    ring.append(label);
  });
  ring.append(svgElement('circle', { cx: 210, cy: 210, r: 189, fill: 'none', stroke: '#d6b073', 'stroke-width': 4 }));
}
function buildBoard() {
  const board = $('bet-board');
  const zero = document.createElement('span');
  zero.className = 'board-cell green zero';
  zero.textContent = '0';
  board.append(zero);
  for (let row = 0; row < 3; row++) {
    for (let col = 0; col < 12; col++) {
      const number = (col + 1) * 3 - row;
      const cell = document.createElement('span');
      cell.className = `board-cell ${pocketColor(number)}`;
      cell.style.gridRow = String(row + 1);
      cell.style.gridColumn = String(col + 2);
      cell.textContent = String(number);
      board.append(cell);
    }
  }
}
function formatTime(value) {
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return '—';
  return Math.max(0, Math.ceil((ms - Date.now() - state.offset) / 1000)).toString().padStart(2, '0');
}
function updateCountdown() {
  const round = state.round;
  if (!round || !['BETTING', 'SPINNING'].includes(round.phase)) return;
  $('countdown').firstChild.textContent = formatTime(round.phase === 'BETTING' ? round.closes_at : round.reveal_at);
}
function displayHistory(recent) {
  const container = $('history');
  container.replaceChildren();
  if (!Array.isArray(recent) || recent.length === 0) {
    container.className = 'history-empty';
    container.textContent = 'No revealed rounds to show.';
    return;
  }
  container.className = 'history-list';
  for (const entry of recent.slice(0, 20)) {
    const pocket = entry.winning_number;
    if (entry.state !== 'VOID_REFUNDED' && (!Number.isInteger(pocket) || pocket < 0 || pocket > 36)) continue;
    const item = document.createElement('span');
    item.className = `history-item ${entry.state === 'VOID_REFUNDED' ? 'void' : pocketColor(pocket)}`;
    item.textContent = entry.state === 'VOID_REFUNDED' ? 'VOID' : String(pocket);
    item.title = entry.state === 'VOID_REFUNDED' ? 'Exceptional void, no result' : `Server result ${pocket}`;
    item.setAttribute('aria-label', item.title);
    container.append(item);
  }
  if (!container.childNodes.length) {
    container.className = 'history-empty';
    container.textContent = 'No revealed rounds to show.';
  }
}
function setResult(number) {
  const orb = $('result-orb');
  orb.className = 'result-orb';
  orb.textContent = number === null ? '—' : String(number);
  if (number === null) {
    $('result-copy').textContent = 'No result has been revealed.';
    $('wheel-ball').classList.remove('revealed');
    return;
  }
  const color = pocketColor(number);
  orb.classList.add(color);
  $('result-copy').textContent = `${color[0].toUpperCase() + color.slice(1)} pocket · selected by the server.`;
  $('wheel-ball').classList.add('revealed');
}
function showSnapshot(payload) {
  $('connection').classList.add('online');
  $('connection-text').textContent = 'Round feed connected';
  state.offset = Date.parse(payload.observed_at) - Date.now();
  state.round = payload.round;
  displayHistory(payload.recent);
  const round = state.round;
  $('round-id').textContent = round?.id ? `#${round.id.slice(0, 8).toUpperCase()}` : '—';
  const phase = round?.phase ?? 'IDLE';
  const labels = {
    IDLE: ['WAITING FOR A ROUND', 'The server has not opened a round yet.'],
    BETTING: ['BETTING WINDOW', 'This read-only preview cannot place a bet.'],
    SPINNING: ['AWAITING REVEAL', 'The server keeps its selected result hidden until reveal.'],
    RESULT_DELAYED: ['RESULT DELAYED', 'Recovery is pending. No outcome will be invented or automatically voided.'],
    RESULT: ['RESULT REVEALED', 'The persisted server-selected pocket is shown below.'],
    VOID: ['ROUND VOID', 'No winning number was recorded for this exceptional incident.'],
  };
  const [title, explanation] = labels[phase] ?? ['ROUND UNAVAILABLE', 'Please wait for the server.'];
  $('round-phase').textContent = title;
  $('phase-explanation').textContent = explanation;
  $('round-phase').classList.toggle('active', phase === 'BETTING' || phase === 'RESULT');
  $('countdown-label').textContent = phase === 'BETTING' ? 'CUTOFF IN' : phase === 'SPINNING' ? 'REVEAL IN' : 'SERVER CLOCK';
  $('countdown').firstChild.textContent = ['BETTING', 'SPINNING'].includes(phase) ? '—' : '—';
  updateCountdown();
  const number = resultFromSnapshot(payload);
  setResult(number);
  if (number !== null && state.lastResultId !== round.id) {
    const target = targetAngle(number, state.angle);
    const ring = $('pocket-ring');
    if (reducedMotion.matches) ring.style.transition = 'none';
    else ring.style.transition = '';
    ring.style.transform = `rotate(${target}deg)`;
    state.angle = target;
    state.lastResultId = round.id;
  }
}
function showUnavailable() {
  $('connection').classList.remove('online');
  $('connection-text').textContent = 'Round feed unavailable';
  $('round-id').textContent = '—';
  $('round-phase').textContent = 'WAITING FOR SERVER';
  $('round-phase').classList.remove('active');
  $('phase-explanation').textContent = 'No live database is connected to this preview. No outcome is simulated.';
  $('countdown-label').textContent = 'SERVER CLOCK';
  $('countdown').firstChild.textContent = '—';
  state.round = null;
  state.lastResultId = null;
  setResult(null);
  displayHistory([]);
}
async function poll() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch('/api/v1/roulette/round', { cache: 'no-store', signal: controller.signal });
    if (!response.ok) throw new Error('Round feed unavailable');
    showSnapshot(await response.json());
  } catch {
    showUnavailable();
  } finally {
    clearTimeout(timeout);
    setTimeout(poll, 2500);
  }
}
buildWheel();
buildBoard();
showUnavailable();
poll();
setInterval(updateCountdown, 250);

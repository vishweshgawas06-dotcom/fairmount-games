// Authentic single-zero European wheel order, clockwise from zero.
// Pure presentation math: the ONLY result input is a persisted server pocket.
export const POCKET_ORDER = Object.freeze([
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23,
  10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
]);
const REDS = new Set([1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]);

export function pocketColor(value) {
  if (!Number.isInteger(value) || value < 0 || value > 36) throw new RangeError('Invalid pocket');
  return value === 0 ? 'green' : REDS.has(value) ? 'red' : 'black';
}

export function resultFromSnapshot(snapshot) {
  const round = snapshot?.round;
  if (round?.phase !== 'RESULT' || typeof round.id !== 'string') return null;
  const number = round.winning_number;
  return Number.isInteger(number) && number >= 0 && number <= 36 ? number : null;
}

export function targetAngle(result, currentAngle = 0) {
  const index = POCKET_ORDER.indexOf(result);
  if (index === -1 || !Number.isFinite(currentAngle)) throw new RangeError('Invalid wheel target');
  const base = -(index * 360 / POCKET_ORDER.length);
  const turns = Math.ceil((currentAngle - base) / 360) + 2;
  return base + turns * 360; // pocket center under the stationary top marker
}

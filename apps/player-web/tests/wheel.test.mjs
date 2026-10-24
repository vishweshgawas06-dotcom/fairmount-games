import assert from 'node:assert/strict';
import test from 'node:test';
import { POCKET_ORDER, pocketColor, resultFromSnapshot, targetAngle } from '../preview/wheel.mjs';

test('European wheel has each pocket exactly once and zero is green', () => {
  assert.equal(POCKET_ORDER.length, 37);
  assert.deepEqual([...POCKET_ORDER].sort((a, b) => a - b), Array.from({ length: 37 }, (_, i) => i));
  assert.equal(pocketColor(0), 'green');
  assert.equal(pocketColor(32), 'red');
  assert.equal(pocketColor(15), 'black');
  for (const invalid of [-1, 37, 1.5, '17']) assert.throws(() => pocketColor(invalid));
});

test('no animation target exists before the server reveals a valid result', () => {
  for (const phase of ['BETTING', 'SPINNING', 'RESULT_DELAYED', 'VOID']) {
    assert.equal(resultFromSnapshot({ round: { id: 'server-id', phase, winning_number: 17 } }), null);
  }
  assert.equal(resultFromSnapshot({ round: { id: 'server-id', phase: 'RESULT', winning_number: 17 } }), 17);
  assert.equal(resultFromSnapshot({ round: { id: 'server-id', phase: 'RESULT', winning_number: 0 } }), 0);
  assert.equal(resultFromSnapshot({ round: { id: 'server-id', phase: 'RESULT', winning_number: 37 } }), null);
  assert.equal(resultFromSnapshot({ round: null }), null);
});

test('every server pocket aligns with top marker regardless of previous rotation', () => {
  for (const value of POCKET_ORDER) {
    for (const previous of [0, 535.5, 4320]) {
      const target = targetAngle(value, previous);
      const actual = ((POCKET_ORDER.indexOf(value) * 360 / 37 + target) % 360 + 360) % 360;
      assert.ok(actual < 1e-8 || 360 - actual < 1e-8, `Pocket ${value} off by ${actual}`);
      assert.ok(target > previous);
    }
  }
  assert.throws(() => targetAngle(37));
  assert.throws(() => targetAngle(17, NaN));
});

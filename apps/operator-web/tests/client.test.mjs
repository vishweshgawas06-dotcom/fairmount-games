import { test } from "node:test";
import assert from "node:assert/strict";
import { ApiError, Command, amount, csrf, points } from "../web/client.mjs";
const cookie = "__Host-fairmount_csrf=" + "A".repeat(43);
const ok = (body) =>
  new Response(
    JSON.stringify({ status: "completed", replayed: false, ...body }),
    { status: 200 },
  );
test("BIGINT display is exact; amounts never silently round", () => {
  assert.equal(
    points("9223372036854775807").replaceAll(",", ""),
    "9223372036854775807",
  );
  assert.equal(amount("9007199254740991"), Number.MAX_SAFE_INTEGER);
  for (const value of [
    "0",
    "-1",
    "1.5",
    "1e3",
    "01",
    "9007199254740992",
    "",
    "Infinity",
    " 10",
  ])
    assert.throws(() => amount(value));
  for (const value of [123, "-1", "1.5", "None"])
    assert.throws(() => points(value));
});
test("single canonical readable CSRF cookie is required", () => {
  assert.equal(csrf("other=x; " + cookie), "A".repeat(43));
  for (const value of [
    "",
    cookie + "; " + cookie,
    cookie + "=",
    "__Host-fairmount_csrf=bad",
  ])
    assert.throws(() => csrf(value));
});
test("network uncertainty retries identical frozen body and idempotency key", async () => {
  const body = { amount: 10, reason: "audited" };
  const command = new Command(
    "/api/v1/operator/points/issue",
    body,
    "stable-key",
  );
  body.amount = 100;
  const calls = [];
  await assert.rejects(
    command.send(cookie, async (...args) => {
      calls.push(args);
      throw Error("connection lost");
    }),
  );
  assert.equal(command.uncertain, true);
  const result = await command.send(cookie, async (...args) => {
    calls.push(args);
    return ok({ replayed: true });
  });
  assert.equal(result.replayed, true);
  assert.equal(command.uncertain, false);
  assert.deepEqual(calls[0], calls[1]);
  assert.equal(JSON.parse(calls[1][1].body).amount, 10);
  assert.equal(calls[1][1].headers["x-csrf-token"], "A".repeat(43));
  assert.equal(calls[1][1].credentials, "same-origin");
});
test("double clicks cannot dispatch a concurrent duplicate", async () => {
  const command = new Command(
    "/api/v1/agent/points/transfer",
    { amount: 1 },
    "key",
  );
  let finish;
  const first = command.send(
    cookie,
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await assert.rejects(command.send(cookie), /already in progress/);
  finish(ok({}));
  await first;
  assert.equal(command.busy, false);
});
test("5xx and malformed success acknowledgments preserve uncertainty", async () => {
  for (const response of [
    new Response("{}", { status: 503 }),
    new Response("invalid JSON", { status: 200 }),
  ]) {
    const command = new Command("/path", {}, "key");
    await assert.rejects(command.send(cookie, async () => response));
    assert.equal(command.uncertain, true);
  }
});
test("known 4xx denial is not a successful or uncertain write", async () => {
  for (const status of [400, 401, 403, 409, 429]) {
    const command = new Command("/path", {}, "key");
    await assert.rejects(
      command.send(cookie, async () => new Response("{}", { status })),
      (error) => error instanceof ApiError && error.status === status,
    );
    assert.equal(command.uncertain, false);
  }
});
test("a denied retry never resolves uncertainty about an earlier write", async () => {
  for (const status of [400, 401, 403, 409, 429]) {
    const command = new Command("/path", {}, "key", "original-actor");
    await assert.rejects(
      command.send(cookie, async () => {
        throw Error("lost acknowledgment");
      }),
    );
    await assert.rejects(
      command.send(cookie, async () => new Response("{}", { status })),
    );
    assert.equal(command.uncertain, true);
    assert.equal(command.actorId, "original-actor");
    await command.send(cookie, async () => ok({ replayed: true }));
    assert.equal(command.uncertain, false);
  }
});
test("local missing proof does not invent a dispatched request; bad acknowledgments do", async () => {
  const command = new Command("/path", {}, "key");
  let dispatched = false;
  await assert.rejects(
    command.send("", async () => {
      dispatched = true;
    }),
  );
  assert.equal(dispatched, false);
  assert.equal(command.uncertain, false);
  await assert.rejects(
    command.send(cookie, async () => new Response("{}", { status: 200 })),
  );
  assert.equal(command.uncertain, true);
});

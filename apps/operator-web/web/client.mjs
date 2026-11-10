// No browser storage: passwords, MFA codes, setup secrets and commands stay in memory.
export function points(value) {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]*)$/.test(value))
    throw Error("Invalid point balance");
  return BigInt(value).toLocaleString("en-IN");
}
export function amount(value) {
  if (!/^[1-9][0-9]*$/.test(value))
    throw Error("Enter a positive whole number of points.");
  const number = Number(value);
  if (!Number.isSafeInteger(number))
    throw Error(
      "This console supports amounts up to 9,007,199,254,740,991 points.",
    );
  return number;
}
export function csrf(cookie) {
  const matches = cookie
    .split(";")
    .map((p) => p.trim().split("="))
    .filter((p) => p[0] === "__Host-fairmount_csrf");
  if (
    matches.length !== 1 ||
    matches[0].length !== 2 ||
    !/^[A-Za-z0-9_-]{43}$/.test(matches[0][1] || "")
  )
    throw Error("Sign in again to refresh security cookies.");
  return matches[0][1];
}
export class ApiError extends Error {
  constructor(status, retryAfter = "") {
    super(
      status === 429
        ? `Too many attempts. Retry after ${retryAfter || "the next window"} seconds.`
        : status === 403
          ? "Not permitted. Check scope, funds and recent owner MFA."
          : status === 401
            ? "Your session or security proof is no longer valid. Sign in again."
            : status === 409
              ? "This request key already belongs to another command. Do not resubmit blindly."
              : status === 400
                ? "Check the fields and try again."
                : "Private access is unavailable. A configured direct-TLS deployment is required.",
    );
    this.status = status;
  }
}
export async function read(path, transport = fetch) {
  const response = await transport(path, {
    credentials: "same-origin",
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok)
    throw new ApiError(response.status, response.headers.get("retry-after"));
  return response.json();
}
export class Command {
  constructor(path, body, key = crypto.randomUUID(), actorId = null) {
    this.actorId = actorId;
    this.path = path;
    this.body = JSON.stringify(body);
    this.key = key;
    this.uncertain = false;
    this.busy = false;
  }
  async send(cookie, transport = fetch) {
    if (this.busy) throw Error("This request is already in progress.");
    const proof = csrf(cookie);
    this.busy = true;
    try {
      const response = await transport(this.path, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: {
          "content-type": "application/json",
          "x-csrf-token": proof,
          "idempotency-key": this.key,
        },
        body: this.body,
      });
      this.uncertain = this.uncertain || response.status >= 500;
      if (!response.ok)
        throw new ApiError(
          response.status,
          response.headers.get("retry-after"),
        );
      const payload = await response.json();
      const statuses = [
        "completed",
        "created",
        "assigned",
        "unassigned",
        "enabled",
        "disabled",
        "setup_secret_reissued",
      ];
      if (
        !payload ||
        !statuses.includes(payload.status) ||
        typeof payload.replayed !== "boolean"
      )
        throw Error("Invalid acknowledgment");
      this.uncertain = false;
      return payload;
    } catch (error) {
      if (!(error instanceof ApiError)) this.uncertain = true;
      throw error;
    } finally {
      this.busy = false;
    }
  }
}

// Mocked browser contract tests, NOT proof of live authentication/deployment.
import { test, expect } from "@playwright/test";
const account = "00000000-0000-4000-8000-000000000001";
const player = {
  account_id: account,
  identifier: "test_player",
  display_name: "<img src=x onerror=alert(1)>",
  role: "PLAYER",
  status: "ENABLED",
  balance: "9223372036854775807",
  agent_account_id: null,
  activation_pending: true,
};
async function mock(page, role = "OWNER", handler) {
  await page.context().addCookies([
    {
      url: "https://localhost:4174/",
      name: "__Host-fairmount_csrf",
      value: "A".repeat(43),
      secure: true,
      sameSite: "Strict",
    },
  ]);
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (handler && (await handler(route, path))) return;
    const data = path.endsWith("/context")
      ? {
          account_id: account,
          role,
          balance: "1234567",
          reserve_balance: "300000",
          observed_at: "2026-10-15T12:00:00Z",
          mfa_refresh_required: false,
        }
      : path.endsWith("/members")
        ? { items: [player], next_after: null }
        : path.endsWith("/history")
          ? { items: [], next_after: null }
          : {};
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(data),
    });
  });
}
test("default deployment denial shows no invented private balances", async ({
  page,
}) => {
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("unavailable");
  await expect(page.locator("#own-balance")).toHaveText("—");
  await expect(page.locator("#owner-tools")).toBeHidden();
  await expect(page.locator("#add-member")).toBeHidden();
});
test("owner roster uses inert text and exact BIGINT display", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await mock(page);
  await page.goto("/");
  await expect(page.locator("#own-balance")).toHaveText("12,34,567");
  await expect(page.locator("#members-body")).toContainText(
    player.display_name,
  );
  await expect(page.locator("#members-body img")).toHaveCount(0);
  await expect(page.locator("#members-body .numeric")).toHaveText(
    "92,23,37,20,36,85,47,75,807",
  );
  await expect(page.locator("#owner-tools")).toBeVisible();
  expect(errors).toEqual([]);
});
test("agent navigation has no owner issuance, reserve or lifecycle controls", async ({
  page,
}) => {
  await mock(page, "AGENT");
  await page.goto("/");
  await expect(page.locator("#role-label")).toHaveText("AGENT");
  await expect(page.locator("#reserve-card")).toBeHidden();
  await expect(page.locator("#owner-tools")).toBeHidden();
  await expect(
    page.getByRole("button", { name: "Disable", exact: true }),
  ).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reissue setup" })).toHaveCount(
    0,
  );
  await page.locator("#add-member").click();
  await expect(page.locator("#field-role")).toHaveCount(0);
  await expect(page.locator("#field-username")).toBeVisible();
});
test("uncertain command retries the original body/key, with CSRF, without duplicate action", async ({
  page,
}) => {
  const writes = [];
  await mock(page, "OWNER", async (route, path) => {
    if (!path.endsWith("/points/issue")) return false;
    writes.push({
      headers: route.request().headers(),
      body: route.request().postData(),
    });
    if (writes.length === 1) await route.abort("failed");
    else
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: '{"status":"completed","replayed":true}',
      });
    return true;
  });
  await page.goto("/");
  await page.locator("#issue").click();
  await page.locator("#field-amount").fill("10");
  await page.locator("#field-reason").fill("browser retry proof");
  await page.getByRole("button", { name: "Review change" }).click();
  await page.locator("#commit-command").click();
  await expect(page.locator("#confirm-error")).toContainText("unknown");
  await expect(page.locator("#cancel-command")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(page.locator("#confirm-dialog")).toBeVisible();
  await page.locator("#commit-command").click();
  await expect(page.locator("#status")).toContainText("Previously recorded");
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toBe(writes[1].body);
  expect(writes[0].headers["idempotency-key"]).toBe(
    writes[1].headers["idempotency-key"],
  );
  expect(writes[0].headers["x-csrf-token"]).toBe("A".repeat(43));
});
test("one-time setup secret is cleared on close and sign-out; no browser storage", async ({
  page,
}) => {
  await mock(page, "OWNER", async (route, path) => {
    if (!path.endsWith("/setup-secret")) return false;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "setup_secret_reissued",
        replayed: false,
        account_id: account,
        secret: "test-only-setup-secret",
        secret_expires_at: "2026-10-16T12:00:00Z",
      }),
    });
    return true;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Reissue setup" }).click();
  await page.locator("#commit-command").click();
  await expect(page.locator("#secret-dialog")).toBeVisible();
  await expect(page.locator("#secret-value")).toHaveValue(
    "test-only-setup-secret",
  );
  await expect(page.locator("#secret-value")).toHaveAttribute(
    "type",
    "password",
  );
  expect(
    await page.evaluate(() => [localStorage.length, sessionStorage.length]),
  ).toEqual([0, 0]);
  await page.keyboard.press("Escape");
  await expect(page.locator("#secret-value")).toHaveValue("");
  await page.locator("#sign-out").click();
  await expect(page.locator("#members-body tr")).toHaveCount(0);
  await expect(page.locator("#own-balance")).toHaveText("—");
});
test("fresh MFA required prompts sign-in without dispatching owner writes", async ({
  page,
}) => {
  await mock(page, "OWNER", async (route, path) => {
    if (!path.endsWith("/context")) return false;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        account_id: account,
        role: "OWNER",
        balance: "1",
        reserve_balance: "1",
        observed_at: "2026-10-15T12:00:00Z",
        mfa_refresh_required: true,
      }),
    });
    return true;
  });
  await page.goto("/");
  await page.locator("#issue").click();
  await expect(page.locator("#login-dialog")).toBeVisible();
  await expect(page.locator("#action-dialog")).toBeHidden();
});
test("phone layout is contained and keyboard can open and dismiss sign-in", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/");
  await expect(page.locator("#status")).toContainText("unavailable");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.locator("#sign-in").focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("#login-password")).toBeFocused();
  await page.locator("#login-password").fill("test-only-password");
  await page.keyboard.press("Escape");
  await expect(page.locator("#login-password")).toHaveValue("");
  await expect(page.locator("#sign-in")).toBeFocused();
});
test("late private read cannot repopulate the view after sign-out", async ({
  page,
}) => {
  let delayed = null,
    delay = false;
  await mock(page, "OWNER", async (route, path) => {
    if (delay && path.endsWith("/context")) {
      delayed = route;
      return true;
    }
    return false;
  });
  await page.goto("/");
  await expect(page.locator("#role-label")).toHaveText("OWNER");
  delay = true;
  await page.locator("#refresh").click();
  await expect.poll(() => Boolean(delayed)).toBe(true);
  await page.locator("#sign-out").click();
  await delayed.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      role: "OWNER",
      balance: "999",
      reserve_balance: "1",
      observed_at: "2026-10-15T12:00:00Z",
    }),
  });
  await expect(page.locator("#own-balance")).toHaveText("—");
  await expect(page.locator("#members-body tr")).toHaveCount(0);
});
test("an unresolved command cannot be replayed as a different operator", async ({
  page,
}) => {
  let changed = false,
    writes = 0;
  await mock(page, "AGENT", async (route, path) => {
    if (path.endsWith("/points/transfer")) {
      writes++;
      await route.abort("failed");
      return true;
    }
    if (path.endsWith("/auth/login")) {
      changed = true;
      await route.fulfill({ status: 200, body: "{}" });
      return true;
    }
    if (changed && path.endsWith("/context")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          account_id: "00000000-0000-4000-8000-000000000002",
          role: "AGENT",
          balance: "5",
          observed_at: "2026-10-15T12:00:00Z",
        }),
      });
      return true;
    }
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Transfer", exact: true }).click();
  await page.locator("#field-amount").fill("1");
  await page.locator("#field-reason").fill("actor binding");
  await page.getByRole("button", { name: "Review change" }).click();
  await page.locator("#commit-command").click();
  await expect(page.locator("#confirm-error")).toContainText("unknown");
  await page.locator("#confirm-login").click();
  await page.locator("#login-role").selectOption("AGENT");
  await page.locator("#login-identifier").fill("AGT-ABCDEFGHJK");
  await page.locator("#login-password").fill("test-password-only");
  await page.locator("#login-submit").click();
  await expect(page.locator("#login-dialog")).toBeHidden();
  await page.locator("#resume-command").click();
  await page.locator("#commit-command").click();
  await expect(page.locator("#confirm-error")).toContainText(
    "original operator",
  );
  expect(writes).toBe(1);
});

test("a session replaced in another tab is checked before any write dispatch", async ({
  page,
}) => {
  let changed = false,
    writes = 0;
  await mock(page, "AGENT", async (route, path) => {
    if (path.endsWith("/points/transfer")) {
      writes++;
      await route.fulfill({ status: 200, body: "{}" });
      return true;
    }
    if (changed && path.endsWith("/context")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          account_id: "00000000-0000-4000-8000-000000000002",
          role: "AGENT",
          balance: "5",
          observed_at: "2026-10-15T12:00:00Z",
        }),
      });
      return true;
    }
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Transfer", exact: true }).click();
  await page.locator("#field-amount").fill("1");
  await page.locator("#field-reason").fill("new-tab session protection");
  await page.getByRole("button", { name: "Review change" }).click();
  changed = true;
  await page.locator("#commit-command").click();
  await expect(page.locator("#status")).toContainText(
    "browser session changed",
  );
  expect(writes).toBe(0);
  await expect(page.locator("#own-balance")).toHaveText("—");
});

test("all owner point and registration forms match exact server contracts", async ({
  page,
}) => {
  const writes = [];
  await mock(page, "OWNER", async (route, path) => {
    if (route.request().method() !== "POST") return false;
    writes.push([path, route.request().postDataJSON()]);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: '{"status":"completed","replayed":false}',
    });
    return true;
  });
  await page.goto("/");
  for (const [id, suffix] of [
    ["issue", "points/issue"],
    ["fund", "reserve/fund"],
    ["withdraw", "reserve/withdraw"],
  ]) {
    await page.locator("#" + id).click();
    await page.locator("#field-amount").fill("25");
    await page.locator("#field-reason").fill("explicit reason");
    await page.getByRole("button", { name: "Review change" }).click();
    await page.locator("#commit-command").click();
    await expect(page.locator("#status")).toContainText("Change confirmed");
    expect(writes.at(-1)).toEqual([
      "/api/v1/operator/" + suffix,
      { amount: 25, reason: "explicit reason" },
    ]);
  }
  for (const role of ["PLAYER", "AGENT"]) {
    await page.locator("#add-member").click();
    await page.locator("#field-role").selectOption(role);
    if (role === "PLAYER")
      await page.locator("#field-username").fill("new_player");
    await page.locator("#field-display_name").fill("Profile Name");
    await page.locator("#field-mobile_number").fill("+91 test contact");
    await page.getByRole("button", { name: "Review change" }).click();
    await page.locator("#commit-command").click();
    await expect(page.locator("#status")).toContainText("Change confirmed");
    expect(writes.at(-1)).toEqual([
      "/api/v1/operator/" + (role === "PLAYER" ? "players" : "agents"),
      {
        display_name: "Profile Name",
        mobile_number: "+91 test contact",
        ...(role === "PLAYER" ? { username: "new_player" } : {}),
      },
    ]);
  }
});

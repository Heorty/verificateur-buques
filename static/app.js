const DEFAULT_FONTS = [
  "Clunsois",
  "Garamond",
  "Helvetica",
  "Times New Roman",
  "Fraktur",
  "Gothic",
  "Old English",
  "Clarendon",
  "Copperplate",
  "Impact",
  "Futura",
  "Courier",
  "Brush Script",
  "Arial",
  "Papyrus",
  "Comic Sans",
];

const state = {
  operator: localStorage.getItem("buques_operator") || "",
  activeTab: "saisie",
  entries: [],
  fonts: [],
  editingId: null,
  lastEntryInput: null,
  comparison: null,
  compareFilter: "all",
  compareSearch: "",
  showFontsInCompare: false,
  sensitivityOverrides: null,
  selectedCell: null, // { entryId, choiceIndex }
  settings: null,
  ws: null,
  lanUrl: "",
};

// ---------------- Utilitaires DOM & API ----------------

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("data-")) node.setAttribute(k, v);
    else if (k === "checked") node.checked = Boolean(v);
    else if (k === "disabled") node.disabled = Boolean(v);
    else node.setAttribute(k, v);
  }
  for (const child of children) {
    if (typeof child === "string") {
      node.appendChild(document.createTextNode(child));
    } else if (child) {
      node.appendChild(child);
    }
  }
  return node;
}

function showToast(message, isError = false) {
  const container = document.getElementById("toast-container");
  const toast = el("div", {
    class: isError ? "toast error" : "toast",
    text: message,
  });
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3200);
}

async function apiFetch(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const contentType = res.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    throw new Error((data && data.error) || `Erreur serveur (${res.status})`);
  }
  return data;
}

function debounce(fn, delayMs) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}

// ---------------- Opérateur & WebSocket ----------------

function ensureOperatorName(forcePrompt = false) {
  if (!state.operator || forcePrompt) {
    const chosen = window.prompt(
      "Ta buque / ton prénom de Gadz' (affiché aux autres Gadz' connectés) :",
      state.operator || "Gadz"
    );
    if (chosen && chosen.trim()) {
      state.operator = chosen.trim().slice(0, 40);
    } else if (!state.operator) {
      state.operator = "Gadz-" + Math.floor(100 + Math.random() * 900);
    }
    localStorage.setItem("buques_operator", state.operator);
  }
  document.getElementById("operator-name-display").textContent = state.operator;
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "hello", user: state.operator }));
  }
}

function connectWebSocket() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${proto}//${window.location.host}/ws`;
  const dot = document.getElementById("ws-status-dot");

  try {
    const ws = new WebSocket(wsUrl);
    state.ws = ws;

    ws.addEventListener("open", () => {
      dot.classList.remove("offline");
      dot.classList.add("online");
      ws.send(JSON.stringify({ type: "hello", user: state.operator || "Opérateur" }));
    });

    ws.addEventListener("message", async (ev) => {
      let msg = null;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!msg) return;

      if (msg.type === "presence") {
        const countEl = document.getElementById("presence-count");
        const namesEl = document.getElementById("presence-names");
        const count = msg.count || 0;
        countEl.textContent = `${count} connecté${count > 1 ? "s" : ""}`;
        const uniqueNames = [...new Set((msg.users || []).map((u) => u.user))];
        namesEl.textContent = uniqueNames.length ? `(${uniqueNames.join(", ")})` : "";
      } else if (msg.type === "entries_changed") {
        await loadEntries();
        if (state.activeTab === "comparaison" || state.comparison) {
          await loadComparison();
        }
      } else if (msg.type === "settings_changed") {
        await loadSettings();
        await loadBddStatus();
        await loadProblematicTerms();
        if (state.activeTab === "comparaison" || state.comparison) {
          await loadComparison();
        }
      } else if (msg.type === "bdd_changed") {
        await loadBddStatus();
        if (state.activeTab === "comparaison" || state.comparison) {
          await loadComparison();
        }
      }
    });

    ws.addEventListener("close", () => {
      dot.classList.remove("online");
      dot.classList.add("offline");
      document.getElementById("presence-count").textContent = "Reconnexion…";
      setTimeout(connectWebSocket, 2500);
    });
  } catch {
    dot.classList.remove("online");
    dot.classList.add("offline");
  }
}

async function loadNetworkInfo() {
  try {
    const data = await apiFetch("/api/network-info");
    const primaryUrl = (data.urls && data.urls[0]) || window.location.origin;
    state.lanUrl = primaryUrl;
    document.getElementById("lan-url-label").textContent = `Wi-Fi : ${primaryUrl}`;
  } catch {
    state.lanUrl = window.location.origin;
    document.getElementById("lan-url-label").textContent = state.lanUrl;
  }
}

// ---------------- Navigation par onglets ----------------

async function switchTab(tabName) {
  state.activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });

  if (tabName === "comparaison") {
    await loadComparison();
  } else if (tabName === "bdd") {
    await Promise.all([loadBddStatus(), loadSettings(), loadProblematicTerms()]);
  }
}

// ---------------- Onglet 1 : Saisie ----------------

function populateFontsDatalist() {
  const dl = document.getElementById("fonts-datalist");
  dl.innerHTML = "";
  const combined = [...new Set([...state.fonts, ...DEFAULT_FONTS])].sort((a, b) =>
    a.localeCompare(b, "fr")
  );
  for (const fontName of combined) {
    dl.appendChild(el("option", { value: fontName }));
  }
}

function checkDuplicateNom() {
  const nom = document.getElementById("input-nom").value.trim().toLowerCase();
  const alertEl = document.getElementById("duplicate-nom-alert");
  if (!nom) {
    alertEl.classList.add("hidden");
    return;
  }
  const dup = state.entries.find(
    (e) => e.nom.trim().toLowerCase() === nom && e.id !== state.editingId
  );
  if (dup) {
    alertEl.textContent = `Attention : « ${dup.nom} » a déjà été saisi (par ${
      dup.updated_by || dup.created_by || "un opérateur"
    }).`;
    alertEl.classList.remove("hidden");
  } else {
    alertEl.classList.add("hidden");
  }
}

const updatePhoneticPreview = debounce(async (inputId, previewId) => {
  const val = document.getElementById(inputId).value.trim();
  const target = document.getElementById(previewId);
  if (!val) {
    target.textContent = "";
    return;
  }
  try {
    const res = await apiFetch("/api/test-buque", {
      method: "POST",
      body: JSON.stringify({ buque: val, preview_only: true }),
    });
    const ph = res.phonetic;
    const readings = (ph.expanded_readings || []).join(" / ");
    const code = ph.primary_phonetic || "";
    target.textContent = readings && readings !== val
      ? `Lecture : ${readings} · Phonétique : [${code}]`
      : `Phonétique : [${code}]`;
  } catch {
    target.textContent = "";
  }
}, 180);

function resetEntryForm() {
  state.editingId = null;
  document.getElementById("entry-form").reset();
  document.getElementById("form-mode-title").innerHTML =
    "Nouvelle fiche de Conscrit (1<sup>re</sup> An'ss)";
  document.getElementById("btn-submit-entry").textContent =
    "Enregistrer la fiche (Entrée)";
  document.getElementById("edit-banner").classList.add("hidden");
  document.getElementById("duplicate-nom-alert").classList.add("hidden");
  ["preview-choix1", "preview-choix2", "preview-choix3"].forEach((id) => {
    document.getElementById(id).textContent = "";
  });
  document.getElementById("input-nom").focus();
}

function startEditingEntry(entryId) {
  const entry = state.entries.find((e) => e.id === entryId);
  if (!entry) return;
  state.editingId = entry.id;
  document.getElementById("input-nom").value = entry.nom || "";
  document.getElementById("input-prenom").value = entry.prenom || "";
  document.getElementById("input-choix1").value = entry.choix1 || "";
  document.getElementById("input-police1").value = entry.police1 || "";
  document.getElementById("input-choix2").value = entry.choix2 || "";
  document.getElementById("input-police2").value = entry.police2 || "";
  document.getElementById("input-choix3").value = entry.choix3 || "";
  document.getElementById("input-police3").value = entry.police3 || "";

  document.getElementById("form-mode-title").textContent = "Modifier une fiche de Conscrit";
  document.getElementById("btn-submit-entry").textContent = "Mettre à jour la fiche";
  document.getElementById("edit-target-name").textContent = entry.nom;
  document.getElementById("edit-banner").classList.remove("hidden");

  updatePhoneticPreview("input-choix1", "preview-choix1");
  updatePhoneticPreview("input-choix2", "preview-choix2");
  updatePhoneticPreview("input-choix3", "preview-choix3");
  window.scrollTo({ top: 0, behavior: "smooth" });
  document.getElementById("input-nom").focus();
}

function renderEntriesTable() {
  const tbody = document.getElementById("entries-tbody");
  tbody.innerHTML = "";
  const q = document.getElementById("entries-search").value.trim().toLowerCase();

  const filtered = state.entries.filter((e) => {
    if (!q) return true;
    const hay = [
      e.nom,
      e.prenom,
      e.choix1,
      e.choix2,
      e.choix3,
      e.police1,
      e.police2,
      e.police3,
    ]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });

  document.getElementById("entries-count-text").textContent = String(state.entries.length);
  document.getElementById("tab-badge-entries").textContent = String(state.entries.length);

  if (filtered.length === 0) {
    const tr = el("tr", {}, [
      el("td", {
        colspan: "6",
        class: "muted",
        text: state.entries.length
          ? "Aucune feuille ne correspond au filtre."
          : "Aucune feuille enregistrée pour le moment. Commencez la saisie ci-dessus.",
      }),
    ]);
    tbody.appendChild(tr);
    return;
  }

  for (const e of filtered) {
    const formatChoiceCell = (buque, police) => {
      const children = [el("strong", { text: buque || "—" })];
      if (police) {
        children.push(el("span", { class: "choice-sub", text: `Police : ${police}` }));
      }
      return el("td", {}, children);
    };

    const nomChildren = [el("strong", { text: e.nom })];
    if (e.prenom) {
      nomChildren.push(el("span", { class: "choice-sub", text: e.prenom }));
    }

    const tr = el("tr", {}, [
      el("td", {}, nomChildren),
      formatChoiceCell(e.choix1, e.police1),
      formatChoiceCell(e.choix2, e.police2),
      formatChoiceCell(e.choix3, e.police3),
      el("td", { text: e.updated_by || e.created_by || "—" }),
      el("td", { class: "cell-actions" }, [
        el("button", {
          type: "button",
          class: "btn btn-sm btn-ghost",
          "data-action": "edit-entry",
          "data-id": String(e.id),
          text: "Modifier",
        }),
        document.createTextNode(" "),
        el("button", {
          type: "button",
          class: "btn btn-sm btn-danger",
          "data-action": "delete-entry",
          "data-id": String(e.id),
          text: "Suppr.",
        }),
      ]),
    ]);
    tbody.appendChild(tr);
  }
}

async function loadEntries() {
  const data = await apiFetch("/api/entries");
  state.entries = data.entries || [];
  state.fonts = data.fonts || [];
  populateFontsDatalist();
  renderEntriesTable();
  checkDuplicateNom();
}

function insertAtCursor(inputEl, snippet) {
  const start = inputEl.selectionStart ?? inputEl.value.length;
  const end = inputEl.selectionEnd ?? inputEl.value.length;
  const before = inputEl.value.slice(0, start);
  const after = inputEl.value.slice(end);
  inputEl.value = before + snippet + after;
  const caret = start + snippet.length;
  inputEl.focus();
  inputEl.setSelectionRange(caret, caret);
  inputEl.dispatchEvent(new Event("input", { bubbles: true }));
}

function replaceTransposeShortcut(inputEl) {
  const val = inputEl.value;
  if (!/\^[tT]/.test(val)) return;
  const pos = inputEl.selectionStart ?? val.length;
  const before = val.slice(0, pos).replace(/\^[tT]/g, "ᵀ");
  const after = val.slice(pos).replace(/\^[tT]/g, "ᵀ");
  inputEl.value = before + after;
  inputEl.setSelectionRange(before.length, before.length);
}

// ---------------- Onglet 2 : Comparaison & Export ----------------

function buildCompareQueryString() {
  const params = new URLSearchParams();
  if (state.sensitivityOverrides) {
    params.set("threshold_r12", String(state.sensitivityOverrides.threshold_r12));
    params.set("threshold_r3", String(state.sensitivityOverrides.threshold_r3));
    params.set("r3_scope", state.sensitivityOverrides.r3_scope);
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function updateExportLinks() {
  const qs = buildCompareQueryString();
  document.getElementById("btn-export-xlsx").href = `/api/export/xlsx${qs}`;
  document.getElementById("btn-export-csv").href = `/api/export/csv${qs}`;
}

async function loadComparison() {
  const qs = buildCompareQueryString();
  updateExportLinks();
  const data = await apiFetch(`/api/compare${qs}`);
  state.comparison = data;
  renderComparison();

  if (state.selectedCell) {
    openInspectorDrawer(state.selectedCell.entryId, state.selectedCell.choiceIndex);
  }
}

function renderComparison() {
  const data = state.comparison;
  if (!data) return;

  const s = data.summary;
  document.getElementById("kpi-students").textContent = String(s.total_students);
  document.getElementById("kpi-vert").textContent = String(s.vert);
  document.getElementById("kpi-rouge").textContent = String(s.rouge);
  document.getElementById("kpi-violet").textContent = String(s.violet);
  document.getElementById("kpi-jaune").textContent = String(s.jaune);
  document.getElementById("kpi-orange").textContent = String(s.orange);
  document.getElementById("kpi-no-green").textContent = String(s.students_without_green);

  const conflictTotal = s.rouge + s.violet + s.jaune + s.orange;
  document.getElementById("tab-badge-conflicts").textContent = String(conflictTotal);

  const tbody = document.getElementById("compare-tbody");
  tbody.innerHTML = "";
  const q = state.compareSearch.trim().toLowerCase();
  const f = state.compareFilter;

  const rows = data.rows.filter((row) => {
    if (q) {
      const hay = [
        row.nom,
        row.prenom,
        ...row.choices.map((c) => `${c.raw} ${c.police}`),
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }

    if (f === "all") return true;
    if (f === "no_green") return !row.has_green;
    if (f === "conflicts") {
      return row.choices.some((c) => c.active_rules && c.active_rules.length > 0);
    }
    return row.choices.some((c) => c.color === f);
  });

  if (rows.length === 0) {
    tbody.appendChild(
      el("tr", {}, [
        el("td", {
          colspan: "4",
          class: "muted",
          text: "Aucune ligne ne correspond à ce filtre.",
        }),
      ])
    );
    return;
  }

  for (const row of rows) {
    const nomLabel = row.prenom ? `${row.nom} (${row.prenom})` : row.nom;
    const tds = [el("td", { class: "compare-nom", text: nomLabel })];

    for (const ch of row.choices) {
      const cellChildren = [
        el("div", { class: "cell-main", text: ch.raw || "—" }),
      ];
      if (state.showFontsInCompare && ch.police) {
        cellChildren.push(
          el("div", { class: "cell-police", text: `Police : ${ch.police}` })
        );
      }
      if (ch.active_rules && ch.active_rules.length > 0) {
        cellChildren.push(
          el(
            "div",
            { class: "cell-dots" },
            ch.active_rules.map((r) => el("span", { class: "rule-tag", text: `R${r}` }))
          )
        );
      }

      const td = el(
        "td",
        {
          class: `compare-cell c-${ch.color}`,
          "data-entry-id": String(row.id),
          "data-choice-index": String(ch.choice_index),
          title: `${ch.label} — Cliquer pour détails`,
        },
        cellChildren
      );
      tds.push(td);
    }

    tbody.appendChild(el("tr", {}, tds));
  }
}

// ---------------- Tiroir d'inspection ----------------

function closeDrawer() {
  state.selectedCell = null;
  document.getElementById("drawer-backdrop").classList.add("hidden");
  document.getElementById("inspect-drawer").classList.add("hidden");
}

function openInspectorDrawer(entryId, choiceIndex) {
  if (!state.comparison) return;
  const row = state.comparison.rows.find((r) => r.id === entryId);
  if (!row) {
    closeDrawer();
    return;
  }
  const ch = row.choices[choiceIndex - 1];
  if (!ch) return;

  state.selectedCell = { entryId, choiceIndex };
  document.getElementById("drawer-student").textContent = `${row.nom}${
    row.prenom ? " " + row.prenom : ""
  } — Choix ${choiceIndex}`;
  document.getElementById("drawer-buque").textContent = ch.raw || "(Non renseigné)";

  const body = document.getElementById("drawer-body");
  body.innerHTML = "";

  // Statut et lectures
  const statusBanner = el("div", { class: `status-banner c-${ch.color}` }, [
    el("span", { text: ch.label }),
    el("span", {
      text: ch.police ? `Police : ${ch.police}` : "Police non renseignée",
    }),
  ]);
  body.appendChild(statusBanner);

  const ph = ch.phonetic || {};
  const phSection = el("div", { class: "drawer-section" }, [
    el("h4", { text: "Analyse phonétique & notations" }),
    el("p", {
      text: `Lectures : ${(ph.expanded_readings || []).join(" / ") || "—"}`,
    }),
    el("p", {
      class: "muted",
      text: `Codes phonétiques : ${(ph.phonetic_readings || []).join(" · ") || "—"}`,
    }),
  ]);
  if (ph.explanation && ph.explanation.length) {
    for (const step of ph.explanation) {
      phSection.appendChild(el("div", { class: "muted", text: `• ${step}` }));
    }
  }
  body.appendChild(phSection);

  const ignoredSet = new Set(ch.ignored_rules || []);

  const renderRuleSection = (ruleNum, title, items, formatter) => {
    if (!items || items.length === 0) return;
    const isIgnored = ignoredSet.has(ruleNum);
    const ignoreToggle = el("label", { class: "toggle-check" }, [
      el("input", {
        type: "checkbox",
        checked: isIgnored,
        "data-ignore-rule": String(ruleNum),
      }),
      el("span", { text: "Ignorer (faux positif)" }),
    ]);

    const sec = el("div", { class: "drawer-section" }, [
      el("h4", {}, [el("span", { text: title }), ignoreToggle]),
    ]);
    for (const item of items) {
      sec.appendChild(formatter(item));
    }
    body.appendChild(sec);
  };

  renderRuleSection(2, "Règle 2 : Surnom de CT", ch.conflicts.r2, (m) =>
    el("div", { class: "match-item" }, [
      el("div", { class: "match-item-top" }, [
        el("span", { text: m.buque }),
        el("span", { text: `${m.score}% (Ortho ${m.ortho_score}% · Phon ${m.phon_score}%)` }),
      ]),
      el("div", {
        class: "match-item-meta",
        text: `CT ${m.annee || ""} ${m.proms ? "· Cl" + m.proms : ""}`,
      }),
    ])
  );

  renderRuleSection(1, "Règle 1 : Même buque en < 10 ans", ch.conflicts.r1, (m) =>
    el("div", { class: "match-item" }, [
      el("div", { class: "match-item-top" }, [
        el("span", { text: m.buque }),
        el("span", { text: `${m.score}% (Ortho ${m.ortho_score}% · Phon ${m.phon_score}%)` }),
      ]),
      el("div", {
        class: "match-item-meta",
        text: `Prom's Cl${m.proms || "?"} · Fam's ${m.fams || "?"} · ${m.nom || ""} ${m.prenom || ""}`,
      }),
    ])
  );

  renderRuleSection(3, "Règle 3 : Ressemblance dans la prom'ss", ch.conflicts.r3, (m) =>
    el("div", { class: "match-item" }, [
      el("div", { class: "match-item-top" }, [
        el("span", { text: `${m.buque} (${m.nom})` }),
        el("span", { text: `${m.score}% (Ortho ${m.ortho_score}% · Phon ${m.phon_score}%)` }),
      ]),
      el("div", {
        class: "match-item-meta",
        text: `Choix ${m.choice_index} de ${m.nom}`,
      }),
    ])
  );

  renderRuleSection(4, "Règle 4 : Référence problématique", ch.conflicts.r4, (m) =>
    el("div", { class: "match-item" }, [
      el("div", { class: "match-item-top" }, [
        el("span", { text: m.category || "Alerte" }),
        el("span", { text: m.manual ? "Manuel" : "Auto" }),
      ]),
      el("div", { class: "match-item-meta", text: m.reason || m.notes || m.term }),
    ])
  );

  // Contrôle manuel Règle 4
  const ov = ch.override || { is_problematic: 0, problematic_reason: "" };
  const r4Control = el("div", { class: "drawer-section" }, [
    el("h4", { text: "Contrôle manuel Règle 4" }),
    el("div", { class: "field" }, [
      el("input", {
        id: "drawer-r4-reason",
        type: "text",
        value: ov.problematic_reason || "",
        placeholder: "Motif éventuel (ex : référence politique/inappropriée)…",
      }),
    ]),
    el("div", { class: "toolbar" }, [
      el("button", {
        type: "button",
        class: "btn btn-sm btn-danger",
        id: "btn-flag-r4",
        text: ov.is_problematic === 1 ? "Mettre à jour le signalement" : "Signaler problématique (R4)",
      }),
      el("button", {
        type: "button",
        class: "btn btn-sm btn-ghost",
        id: "btn-clear-r4",
        text: "Marquer R4 OK",
      }),
    ]),
  ]);
  body.appendChild(r4Control);

  // Info : PGs anciens (> 10 An'ss)
  if (ch.conflicts.older_pgs && ch.conflicts.older_pgs.length > 0) {
    const olderSec = el("div", { class: "drawer-section" }, [
      el("h4", { text: "Info : Anciens PGs (> 10 An'ss, autorisé par la Règle 1)" }),
    ]);
    for (const m of ch.conflicts.older_pgs) {
      olderSec.appendChild(
        el("div", { class: "match-item" }, [
          el("div", { class: "match-item-top" }, [
            el("span", { text: m.buque }),
            el("span", { text: `Cl${m.proms || "?"}` }),
          ]),
          el("div", {
            class: "match-item-meta",
            text: `${m.nom || ""} ${m.prenom || ""} · Fam's ${m.fams || "?"}`,
          }),
        ])
      );
    }
    body.appendChild(olderSec);
  }

  // Écouteurs dans le tiroir
  body.querySelectorAll("input[data-ignore-rule]").forEach((cb) => {
    cb.addEventListener("change", async () => {
      const nextIgnored = [];
      body.querySelectorAll("input[data-ignore-rule]").forEach((box) => {
        if (box.checked) nextIgnored.push(Number(box.dataset.ignoreRule));
      });
      await saveOverrideFromDrawer(entryId, choiceIndex, ov.is_problematic, ov.problematic_reason, nextIgnored);
    });
  });

  document.getElementById("btn-flag-r4").addEventListener("click", async () => {
    const reason = document.getElementById("drawer-r4-reason").value.trim();
    const nextIgnored = [...ignoredSet].filter((r) => r !== 4);
    await saveOverrideFromDrawer(entryId, choiceIndex, 1, reason, nextIgnored);
    showToast("Référence signalée en Règle 4.");
  });

  document.getElementById("btn-clear-r4").addEventListener("click", async () => {
    await saveOverrideFromDrawer(entryId, choiceIndex, -1, "", [...ignoredSet]);
    showToast("Règle 4 retirée pour ce choix.");
  });

  document.getElementById("drawer-backdrop").classList.remove("hidden");
  document.getElementById("inspect-drawer").classList.remove("hidden");
}

async function saveOverrideFromDrawer(entryId, choiceIndex, isProblematic, reason, ignoredRules) {
  await apiFetch(`/api/overrides/${entryId}/${choiceIndex}`, {
    method: "PUT",
    body: JSON.stringify({
      is_problematic: isProblematic,
      problematic_reason: reason,
      ignored_rules: ignoredRules,
      user: state.operator,
    }),
  });
  await loadComparison();
}

// ---------------- Onglet 3 : Testeur phonétique ----------------

const runTester = debounce(async () => {
  const val = document.getElementById("tester-input").value.trim();
  const container = document.getElementById("tester-results");
  if (!val) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }
  try {
    const res = await apiFetch("/api/test-buque", {
      method: "POST",
      body: JSON.stringify({ buque: val }),
    });
    container.classList.remove("hidden");
    container.innerHTML = "";

    container.appendChild(
      el("div", { class: `status-banner c-${res.color}` }, [
        el("span", { text: `Verdict : ${res.label}` }),
        el("span", {
          text: `Phonétique : [${res.phonetic.primary_phonetic}]`,
        }),
      ])
    );

    const phCard = el("div", { class: "match-item" }, [
      el("div", {
        text: `Lectures interprétées : ${(res.phonetic.expanded_readings || []).join(" / ")}`,
      }),
      el("div", {
        class: "match-item-meta",
        text: `Variantes phonétiques : ${(res.phonetic.phonetic_readings || []).join(" · ")}`,
      }),
    ]);
    for (const step of res.phonetic.explanation || []) {
      phCard.appendChild(el("div", { class: "match-item-meta", text: `• ${step}` }));
    }
    container.appendChild(phCard);

    const renderGroup = (title, items, fmt) => {
      if (!items || !items.length) return;
      const box = el("div", { class: "drawer-section" }, [
        el("h4", { text: `${title} (${items.length})` }),
      ]);
      for (const it of items) box.appendChild(fmt(it));
      container.appendChild(box);
    };

    renderGroup("Règle 2 : CTs", res.conflicts.r2, (m) =>
      el("div", { class: "match-item" }, [
        el("strong", { text: `${m.buque} — ${m.score}%` }),
        el("div", { class: "match-item-meta", text: `CT ${m.annee || ""} · Cl${m.proms || "?"}` }),
      ])
    );
    renderGroup("Règle 1 : PGs (< 10 ans)", res.conflicts.r1, (m) =>
      el("div", { class: "match-item" }, [
        el("strong", { text: `${m.buque} — ${m.score}%` }),
        el("div", { class: "match-item-meta", text: `Cl${m.proms || "?"} · ${m.nom} ${m.prenom} · Fam's ${m.fams}` }),
      ])
    );
    renderGroup("Règle 3 : Feuilles actuelles", res.conflicts.r3, (m) =>
      el("div", { class: "match-item" }, [
        el("strong", { text: `${m.buque} (${m.nom}, Choix ${m.choice_index}) — ${m.score}%` }),
      ])
    );
    renderGroup("Règle 4 : Références problématiques", res.conflicts.r4, (m) =>
      el("div", { class: "match-item" }, [
        el("strong", { text: `${m.category} : ${m.reason}` }),
      ])
    );
    renderGroup("Info : Anciens PGs (> 10 ans)", res.conflicts.older_pgs, (m) =>
      el("div", { class: "match-item" }, [
        el("strong", { text: `${m.buque} (Cl${m.proms || "?"})` }),
        el("div", { class: "match-item-meta", text: `${m.nom} ${m.prenom} · Fam's ${m.fams}` }),
      ])
    );
  } catch (err) {
    showToast(err.message, true);
  }
}, 220);

// ---------------- Onglet 4 : BDD & Paramètres ----------------

async function loadSettings() {
  const data = await apiFetch("/api/settings");
  const s = data.settings;
  state.settings = s;

  document.getElementById("header-proms-badge").textContent = `Cl${s.current_proms}`;
  document.getElementById("set-current-proms").value = s.current_proms;
  document.getElementById("set-rule1-years").value = s.rule1_years;
  document.getElementById("set-thresh-r12").value = Math.round(s.threshold_r12 * 100);
  document.getElementById("set-thresh-r3").value = Math.round(s.threshold_r3 * 100);

  if (!state.sensitivityOverrides) {
    document.getElementById("slider-r12").value = Math.round(s.threshold_r12 * 100);
    document.getElementById("val-r12").textContent = `${Math.round(s.threshold_r12 * 100)}%`;
    document.getElementById("slider-r3").value = Math.round(s.threshold_r3 * 100);
    document.getElementById("val-r3").textContent = `${Math.round(s.threshold_r3 * 100)}%`;
    document.getElementById("select-r3-scope").value = s.r3_scope;
  }
}

async function loadBddStatus() {
  const stats = await apiFetch("/api/bdd/status");
  const banner = document.getElementById("bdd-default-banner");
  if (stats.default_file_loaded) {
    banner.textContent = `Base par défaut chargée : bdd/${stats.default_file_name}`;
    banner.style.background = "#ecfdf5";
    banner.style.color = "#065f46";
    banner.style.borderColor = "#6ee7b7";
    banner.classList.remove("hidden");
  } else {
    banner.textContent = `Aucun fichier bdd/${stats.default_file_name} détecté. Placez-le dans bdd/ ou importez votre tableau (.xlsx / .csv) ci-dessous.`;
    banner.style.background = "#fef3c7";
    banner.style.color = "#92400e";
    banner.style.borderColor = "#fcd34d";
    banner.classList.remove("hidden");
  }
  const cards = document.getElementById("bdd-health-cards");
  cards.innerHTML = "";
  cards.appendChild(
    el("div", { class: "bdd-stat-box" }, [
      el("strong", { text: String(stats.total_pgs) }),
      el("span", { class: "muted", text: "PGs Clun'ssois chargés (total)" }),
    ])
  );
  cards.appendChild(
    el("div", { class: "bdd-stat-box" }, [
      el("strong", { text: String(stats.total_recent_pgs) }),
      el("span", {
        class: "muted",
        text: `PGs Règle 1 (Cl${stats.window_start}–Cl${stats.window_end})`,
      }),
    ])
  );
  cards.appendChild(
    el("div", { class: "bdd-stat-box" }, [
      el("strong", { text: String(stats.total_cts) }),
      el("span", { class: "muted", text: "CTs chargés (Règle 2)" }),
    ])
  );

  const cov = document.getElementById("bdd-proms-coverage");
  cov.innerHTML = "";
  const entries = Object.entries(stats.recent_proms_counts || {}).sort(
    (a, b) => Number(a[0]) - Number(b[0])
  );
  for (const [p, cnt] of entries) {
    cov.appendChild(
      el("span", {
        class: cnt === 0 ? "prom-chip missing" : "prom-chip",
        text: cnt === 0 ? `Cl${p} : 0 (manquante)` : `Cl${p} : ${cnt}`,
      })
    );
  }

  const batchesEl = document.getElementById("bdd-extra-batches");
  batchesEl.innerHTML = "";
  if (stats.extra_batches && stats.extra_batches.length) {
    batchesEl.appendChild(el("p", { class: "muted", text: "Imports supplémentaires actifs :" }));
    for (const b of stats.extra_batches) {
      batchesEl.appendChild(
        el("div", { class: "match-item" }, [
          el("div", { class: "match-item-top" }, [
            el("span", { text: `${b.batch_name} (${b.kind.toUpperCase()}, ${b.count} lignes)` }),
            el("button", {
              type: "button",
              class: "btn btn-sm btn-danger",
              "data-delete-batch": b.batch_name,
              text: "Retirer",
            }),
          ]),
        ])
      );
    }
  }
}

async function runBddSearch() {
  const q = document.getElementById("bdd-search-input").value.trim();
  const kind = document.getElementById("bdd-search-kind").value;
  const out = document.getElementById("bdd-search-results");
  if (!q) {
    out.innerHTML = "";
    return;
  }
  const data = await apiFetch(
    `/api/bdd/search?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}`
  );
  out.innerHTML = "";
  if (!data.results.length) {
    out.appendChild(el("p", { class: "muted", text: "Aucun résultat." }));
    return;
  }
  for (const r of data.results) {
    out.appendChild(
      el("div", { class: "match-item" }, [
        el("div", { class: "match-item-top" }, [
          el("span", { text: `[${r.kind.toUpperCase()}] ${r.buque}` }),
          el("span", { text: `${r.score}% · ${r.proms ? "Cl" + r.proms : r.annee}` }),
        ]),
        el("div", {
          class: "match-item-meta",
          text: `${r.nom} ${r.prenom} · Fam's ${r.fams || "?"} · [${r.phonetic}]`,
        }),
      ])
    );
  }
}

async function loadProblematicTerms() {
  const data = await apiFetch("/api/problematic-terms");
  const container = document.getElementById("terms-list");
  container.innerHTML = "";
  for (const t of data.terms || []) {
    container.appendChild(
      el("span", { class: "term-chip", title: `${t.category} — ${t.notes || ""}` }, [
        el("span", { text: `${t.term} (${t.category})` }),
        el("button", {
          type: "button",
          class: "term-del",
          "data-delete-term": String(t.id),
          title: "Supprimer ce terme",
          text: "×",
        }),
      ])
    );
  }
}

// ---------------- Initialisation des écouteurs ----------------

function initEventListeners() {
  // Opérateur & Partage Wi-Fi
  document.getElementById("btn-operator").addEventListener("click", () => {
    ensureOperatorName(true);
  });

  document.getElementById("btn-share-lan").addEventListener("click", async () => {
    const url = state.lanUrl || window.location.origin;
    try {
      await navigator.clipboard.writeText(url);
      showToast(`Adresse copiée : ${url}`);
    } catch {
      window.prompt("Partagez cette adresse sur le réseau Wi-Fi :", url);
    }
  });

  // Onglets
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });
  document.getElementById("btn-go-compare").addEventListener("click", () => {
    switchTab("comparaison");
  });

  // Suivi du champ actif pour les boutons d'insertion rapide
  document.querySelectorAll(".buque-input").forEach((inp) => {
    inp.addEventListener("focus", () => {
      state.lastEntryInput = inp;
    });
  });

  document.querySelectorAll(".sym-btn").forEach((btn) => {
    btn.addEventListener("mousedown", (ev) => ev.preventDefault());
    btn.addEventListener("click", () => {
      const sym = btn.dataset.insert;
      if (btn.dataset.targetGroup === "tester") {
        insertAtCursor(document.getElementById("tester-input"), sym);
      } else {
        const target =
          state.lastEntryInput || document.getElementById("input-choix1");
        insertAtCursor(target, sym);
      }
    });
  });

  // Vérifications live en saisie (+ conversion ^T -> ᵀ)
  document.getElementById("input-nom").addEventListener("input", checkDuplicateNom);
  [1, 2, 3].forEach((idx) => {
    const inp = document.getElementById(`input-choix${idx}`);
    inp.addEventListener("input", () => {
      replaceTransposeShortcut(inp);
      updatePhoneticPreview(`input-choix${idx}`, `preview-choix${idx}`);
    });
  });

  // Soumission formulaire feuille
  document.getElementById("entry-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const payload = {
      nom: document.getElementById("input-nom").value.trim(),
      prenom: document.getElementById("input-prenom").value.trim(),
      choix1: document.getElementById("input-choix1").value.trim(),
      police1: document.getElementById("input-police1").value.trim(),
      choix2: document.getElementById("input-choix2").value.trim(),
      police2: document.getElementById("input-police2").value.trim(),
      choix3: document.getElementById("input-choix3").value.trim(),
      police3: document.getElementById("input-police3").value.trim(),
      user: state.operator,
    };
    if (!payload.nom) {
      showToast("Le nom de famille est obligatoire.", true);
      return;
    }

    try {
      const wasEditing = state.editingId !== null;
      if (wasEditing) {
        await apiFetch(`/api/entries/${state.editingId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        showToast(`Fiche de ${payload.nom} mise à jour.`);
      } else {
        await apiFetch("/api/entries", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        showToast(`Fiche de ${payload.nom} enregistrée !`);
      }

      const formCard = document.querySelector(".form-card");
      formCard.classList.remove("flash-saved");
      void formCard.offsetWidth;
      formCard.classList.add("flash-saved");

      resetEntryForm();
      await loadEntries();
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("btn-clear-form").addEventListener("click", resetEntryForm);
  document.getElementById("btn-cancel-edit").addEventListener("click", resetEntryForm);
  document.getElementById("entries-search").addEventListener("input", renderEntriesTable);

  // Actions modifier/supprimer dans le tableau des feuilles
  document.getElementById("entries-tbody").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-action]");
    if (!btn) return;
    const id = Number(btn.dataset.id);
    if (btn.dataset.action === "edit-entry") {
      startEditingEntry(id);
    } else if (btn.dataset.action === "delete-entry") {
      const entry = state.entries.find((e) => e.id === id);
      if (!window.confirm(`Supprimer la feuille de ${entry ? entry.nom : "#" + id} ?`)) {
        return;
      }
      try {
        await apiFetch(
          `/api/entries/${id}?user=${encodeURIComponent(state.operator)}`,
          { method: "DELETE" }
        );
        if (state.editingId === id) resetEntryForm();
        await loadEntries();
        showToast("Feuille supprimée.");
      } catch (err) {
        showToast(err.message, true);
      }
    }
  });

  // Import CSV feuilles
  document.getElementById("entries-csv-file").addEventListener("change", async (ev) => {
    const file = ev.target.files[0];
    if (!file) return;
    try {
      const csvText = await file.text();
      const res = await apiFetch("/api/entries/import", {
        method: "POST",
        body: JSON.stringify({ csv_text: csvText, user: state.operator }),
      });
      await loadEntries();
      showToast(`${res.imported} feuille(s) importée(s).`);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      ev.target.value = "";
    }
  });

  // Filtres et contrôles de l'onglet Comparaison
  const setCompareFilter = (filterVal) => {
    state.compareFilter = filterVal;
    document.querySelectorAll(".filter-pill").forEach((p) => {
      p.classList.toggle("active", p.dataset.filter === filterVal);
    });
    renderComparison();
  };

  document.getElementById("compare-filter-pills").addEventListener("click", (ev) => {
    const pill = ev.target.closest(".filter-pill");
    if (pill) setCompareFilter(pill.dataset.filter);
  });
  document.getElementById("kpi-grid").addEventListener("click", (ev) => {
    const card = ev.target.closest(".kpi-card");
    if (card) setCompareFilter(card.dataset.filter);
  });

  document.getElementById("compare-search").addEventListener("input", (ev) => {
    state.compareSearch = ev.target.value;
    renderComparison();
  });

  document.getElementById("toggle-show-fonts").addEventListener("change", (ev) => {
    state.showFontsInCompare = ev.target.checked;
    renderComparison();
  });

  document.getElementById("btn-toggle-sensitivity").addEventListener("click", () => {
    document.getElementById("sensitivity-panel").classList.toggle("hidden");
  });

  const onSensitivityInput = debounce(() => {
    const r12 = Number(document.getElementById("slider-r12").value) / 100;
    const r3 = Number(document.getElementById("slider-r3").value) / 100;
    const scope = document.getElementById("select-r3-scope").value;
    document.getElementById("val-r12").textContent = `${Math.round(r12 * 100)}%`;
    document.getElementById("val-r3").textContent = `${Math.round(r3 * 100)}%`;
    state.sensitivityOverrides = {
      threshold_r12: r12,
      threshold_r3: r3,
      r3_scope: scope,
    };
    loadComparison();
  }, 180);

  document.getElementById("slider-r12").addEventListener("input", onSensitivityInput);
  document.getElementById("slider-r3").addEventListener("input", onSensitivityInput);
  document.getElementById("select-r3-scope").addEventListener("change", onSensitivityInput);

  document.getElementById("btn-save-sensitivity").addEventListener("click", async () => {
    if (!state.sensitivityOverrides) return;
    try {
      await apiFetch("/api/settings", {
        method: "PUT",
        body: JSON.stringify(state.sensitivityOverrides),
      });
      state.sensitivityOverrides = null;
      await loadSettings();
      await loadComparison();
      showToast("Seuils enregistrés comme valeurs par défaut.");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("btn-print").addEventListener("click", () => window.print());

  // Clic sur une cellule du tableau comparatif -> ouverture tiroir
  document.getElementById("compare-tbody").addEventListener("click", (ev) => {
    const cell = ev.target.closest("td.compare-cell");
    if (!cell) return;
    openInspectorDrawer(
      Number(cell.dataset.entryId),
      Number(cell.dataset.choiceIndex)
    );
  });

  document.getElementById("btn-close-drawer").addEventListener("click", closeDrawer);
  document.getElementById("drawer-backdrop").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeDrawer();
  });

  // Testeur phonétique
  const testerInp = document.getElementById("tester-input");
  testerInp.addEventListener("input", () => {
    replaceTransposeShortcut(testerInp);
    runTester();
  });
  document.querySelectorAll(".example-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const inp = document.getElementById("tester-input");
      inp.value = chip.dataset.example;
      runTester();
    });
  });

  // BDD & Paramètres
  document.getElementById("settings-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try {
      await apiFetch("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          current_proms: Number(document.getElementById("set-current-proms").value),
          rule1_years: Number(document.getElementById("set-rule1-years").value),
          threshold_r12: Number(document.getElementById("set-thresh-r12").value) / 100,
          threshold_r3: Number(document.getElementById("set-thresh-r3").value) / 100,
        }),
      });
      state.sensitivityOverrides = null;
      await loadSettings();
      await loadBddStatus();
      showToast("Paramètres enregistrés.");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("btn-bdd-search").addEventListener("click", runBddSearch);
  document.getElementById("bdd-search-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      runBddSearch();
    }
  });

  document.getElementById("bdd-import-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const file = document.getElementById("bdd-import-file").files[0];
    if (!file) return;
    try {
      const buf = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      const chunk = 0x8000;
      for (let i = 0; i < buf.length; i += chunk) {
        bin += String.fromCharCode(...buf.subarray(i, i + chunk));
      }
      const contentB64 = btoa(bin);
      const res = await apiFetch("/api/bdd/import", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          mode: document.getElementById("bdd-import-kind").value,
          proms: document.getElementById("bdd-import-proms").value || null,
          batch_name: document.getElementById("bdd-import-batch").value.trim(),
          content_b64: contentB64,
        }),
      });
      ev.target.reset();
      await loadBddStatus();
      showToast(`${res.imported} ligne(s) ajoutée(s) à la BDD.`);
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("bdd-extra-batches").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-delete-batch]");
    if (!btn) return;
    const bname = btn.dataset.deleteBatch;
    try {
      await apiFetch(`/api/bdd/batch/${encodeURIComponent(bname)}`, {
        method: "DELETE",
      });
      await loadBddStatus();
      showToast(`Lot « ${bname} » retiré.`);
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("term-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const term = document.getElementById("term-input").value.trim();
    const category = document.getElementById("term-category").value.trim();
    if (!term) return;
    try {
      await apiFetch("/api/problematic-terms", {
        method: "POST",
        body: JSON.stringify({ term, category }),
      });
      document.getElementById("term-input").value = "";
      await loadProblematicTerms();
      showToast(`Terme « ${term} » ajouté à la Règle 4.`);
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById("terms-list").addEventListener("click", async (ev) => {
    const btn = ev.target.closest("button[data-delete-term]");
    if (!btn) return;
    try {
      await apiFetch(`/api/problematic-terms/${btn.dataset.deleteTerm}`, {
        method: "DELETE",
      });
      await loadProblematicTerms();
    } catch (err) {
      showToast(err.message, true);
    }
  });
}

// ---------------- Démarrage ----------------

async function boot() {
  initEventListeners();
  ensureOperatorName(false);
  connectWebSocket();
  await Promise.all([loadNetworkInfo(), loadSettings(), loadEntries()]);
  document.getElementById("input-nom").focus();
}

boot().catch((err) => {
  console.error(err);
  showToast("Erreur d'initialisation de l'application.", true);
});

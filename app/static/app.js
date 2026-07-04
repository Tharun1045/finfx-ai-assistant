async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

function money(value, currency = "GBP") {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(value);
}

function renderJson(value) {
  return JSON.stringify(value, null, 2);
}

let liveRateData = null;
let selectedRateGroup = "GBP";
let databaseStatus = null;
const demoAdminCredentials = {
  username: "admin@finfx.local",
  password: "FinFXAdmin123",
};

async function loadSummary() {
  let transfers = [];
  try {
    const result = await request("/api/transfers?limit=500");
    transfers = result.transfers || [];
  } catch (error) {
    document.querySelector("#total-volume").textContent = "Unavailable";
    document.querySelector("#total-count").textContent = "0";
    document.querySelector("#top-pair").textContent = "No SQL";
    document.querySelector("#flagged-count").textContent = "0";
    document.querySelector("#status-bars").innerHTML = `<p class="source-note">Supabase transfers could not be loaded.</p>`;
    return;
  }
  const today = new Date().toISOString().slice(0, 10);
  const totalVolume = transfers.reduce((sum, transfer) => sum + Number(transfer.amount || 0), 0);
  const todayCount = transfers.filter((transfer) => String(transfer.created_at || "").slice(0, 10) === today).length;
  const corridorTotals = transfers.reduce((groups, transfer) => {
    const pair = `${transfer.from_currency}/${transfer.to_currency}`;
    groups[pair] = (groups[pair] || 0) + Number(transfer.amount || 0);
    return groups;
  }, {});
  const topCorridor = Object.entries(corridorTotals).sort((a, b) => b[1] - a[1])[0];

  document.querySelector("#total-volume").textContent = totalVolume.toLocaleString(undefined, { maximumFractionDigits: 2 });
  document.querySelector("#total-count").textContent = transfers.length.toLocaleString();
  document.querySelector("#top-pair").textContent = topCorridor ? topCorridor[0] : "No records";
  document.querySelector("#flagged-count").textContent = todayCount.toLocaleString();

  const max = Math.max(...Object.values(corridorTotals), 1);
  const bars = Object.entries(corridorTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([pair, amount]) => `
    <div class="bar-row">
      <span>${pair}</span>
      <div class="bar-track"><div class="bar-fill" style="width: ${(amount / max) * 100}%"></div></div>
      <strong>${amount.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
    </div>
  `).join("");
  document.querySelector("#status-bars").innerHTML = bars || `<p class="source-note">No Supabase transfer records yet.</p>`;
}

async function loadDatabaseStatus() {
  databaseStatus = await request("/api/database/status");
  const pill = document.querySelector("#database-pill");
  const alert = document.querySelector("#db-alert");

  if (databaseStatus.available) {
    pill.textContent = `${databaseStatus.provider} active`;
    pill.className = "pill success";
    alert.classList.add("hidden");
    alert.textContent = "";
    return;
  }

  pill.textContent = `${databaseStatus.provider} unavailable`;
  pill.className = "pill warning";
  alert.classList.remove("hidden");
  alert.innerHTML = `
    <strong>Supabase/database is not available.</strong>
    <span>${escapeHtml(databaseStatus.message)} ${escapeHtml(databaseStatus.next_steps?.[0] || "Check DATABASE_URL and restart the API.")}</span>
  `;
}

async function loadLiveRates() {
  const body = document.querySelector("#live-rates-body");
  body.innerHTML = `<tr><td colspan="5">Loading live rates...</td></tr>`;

  try {
    liveRateData = await request("/api/fx/live-rates");
    renderLiveRates();
  } catch (error) {
    body.innerHTML = `<tr><td colspan="5">Unable to load live rates. Please try again shortly.</td></tr>`;
  }
}

async function loadProviders() {
  const grid = document.querySelector("#provider-grid");
  try {
    const result = await request("/api/providers/status");
    const providers = [...result.active_without_keys, ...result.optional_api_key_providers];
    grid.innerHTML = providers.map((provider) => `
      <article class="provider-card ${provider.configured ? "configured" : ""}">
        <div class="provider-card-head">
          <strong>${provider.provider}</strong>
          <span class="pill ${provider.configured ? "success" : "warning"}">${provider.configured ? "Active" : "Needs key"}</span>
        </div>
        <p>${provider.requires_api_key ? "API key provider" : "No API key required"}</p>
        <small>${(provider.capabilities || []).join(", ")}</small>
      </article>
    `).join("");
  } catch (error) {
    grid.innerHTML = `<article class="provider-card"><strong>Unable to load provider status.</strong></article>`;
  }
}

async function loadLlmUsage() {
  const grid = document.querySelector("#llm-usage-grid");
  const recent = document.querySelector("#llm-usage-recent");
  try {
    const usage = await request("/api/llm/usage");
    const totals = usage.totals || {};
    grid.innerHTML = `
      <article class="provider-card configured">
        <strong>${Number(totals.calls || 0).toLocaleString()}</strong>
        <p>LLM/embed calls</p>
        <small>${Number(totals.successful_calls || 0).toLocaleString()} successful, ${Number(totals.failed_calls || 0).toLocaleString()} failed</small>
      </article>
      <article class="provider-card">
        <strong>${Number(totals.total_tokens || 0).toLocaleString()}</strong>
        <p>Estimated tokens</p>
        <small>${Number(totals.input_tokens || 0).toLocaleString()} input, ${Number(totals.output_tokens || 0).toLocaleString()} output</small>
      </article>
      ${Object.entries(usage.by_provider || {}).map(([provider, row]) => `
        <article class="provider-card">
          <strong>${escapeHtml(provider)}</strong>
          <p>${Number(row.calls || 0).toLocaleString()} calls</p>
          <small>${Number(row.total_tokens || 0).toLocaleString()} estimated tokens</small>
        </article>
      `).join("")}
    `;

    recent.innerHTML = (usage.recent || []).map((record) => `
      <article class="usage-row">
        <span>${escapeHtml(record.call_type)}</span>
        <strong>${escapeHtml(record.provider)} / ${escapeHtml(record.model)}</strong>
        <small>${Number(record.total_tokens || 0).toLocaleString()} tokens &middot; ${record.success ? "success" : "failed"}</small>
      </article>
    `).join("") || `<p class="source-note">Ask AI to start logging model calls.</p>`;
  } catch (error) {
    grid.innerHTML = `<article class="provider-card"><strong>Unable to load LLM usage.</strong></article>`;
    recent.innerHTML = "";
  }
}

function renderLiveRates() {
  if (!liveRateData) return;
  const rows = liveRateData.groups[selectedRateGroup] || [];
  const body = document.querySelector("#live-rates-body");
  body.innerHTML = rows.map((row) => {
    if (row.error) {
      return `<tr><td>${row.pair}</td><td colspan="4">${row.error}</td></tr>`;
    }

    const direction = row.change === null ? "flat" : row.change > 0 ? "up" : row.change < 0 ? "down" : "flat";
    const arrow = direction === "up" ? "&uarr;" : direction === "down" ? "&darr;" : "&bull;";
    const changeValue = row.change === null ? "n/a" : `${row.change > 0 ? "+" : ""}${row.change.toLocaleString()}`;
    const varianceValue = row.change_percent === null ? "n/a" : `${row.change_percent > 0 ? "+" : ""}${row.change_percent.toLocaleString()}%`;

    return `
      <tr>
        <td><strong>${row.pair}</strong></td>
        <td>${row.latest_rate.toLocaleString()}<small>${row.latest_date || ""}</small></td>
        <td>${row.previous_rate === null ? "n/a" : row.previous_rate.toLocaleString()}<small>${row.previous_date || ""}</small></td>
        <td class="${direction}"><span class="trend-arrow ${direction}">${arrow}</span>${changeValue}</td>
        <td><span class="variance ${direction}"><span class="trend-arrow ${direction}">${arrow}</span>${varianceValue}</span></td>
      </tr>
    `;
  }).join("");

  document.querySelector("#live-rates-source").textContent = `${liveRateData.provider}; latest available market observations.`;
}

async function askKnowledge() {
  const question = document.querySelector("#knowledge-question").value.trim();
  const useLlm = document.querySelector("#use-llm").checked;
  const answerEl = document.querySelector("#knowledge-answer");
  const evidenceEl = document.querySelector("#retrieval-evidence");

  if (!question) {
    answerEl.innerHTML = `<p>Type a question first.</p>`;
    evidenceEl.innerHTML = "";
    document.querySelector("#rag-mode").textContent = "Assistant ready";
    document.querySelector("#rag-detail").textContent = "Ask to run Ollama/RAG";
    return;
  }

  answerEl.innerHTML = `<div class="loading-line"></div><p>Retrieving knowledge and asking the local model...</p>`;
  evidenceEl.innerHTML = "";

  try {
    const result = await request("/api/knowledge/ask", {
      method: "POST",
      body: JSON.stringify({ question, use_llm: useLlm }),
    });

    const modeLabel = result.mode === "ollama-pgvector-rag"
      ? "Ollama pgvector RAG"
      : result.mode === "ollama-rag" ? "Ollama RAG" : result.mode === "fx-tool" ? "Live FX tool" : result.mode.replace("-", " ");
    document.querySelector("#rag-mode").textContent = modeLabel;
    document.querySelector("#rag-detail").textContent = result.mode === "fx-tool"
      ? "Answered with market data"
      : result.mode === "llm-tool-agent" ? "Ollama selected a safe tool"
      : result.mode === "ollama-pgvector-rag" ? "LLM grounded on Supabase vectors"
      : result.llm_available ? "LLM grounded on retrieved docs" : "Retrieval fallback active";

    answerEl.innerHTML = renderAssistantAnswer(result, modeLabel);
    await loadLlmUsage();

    evidenceEl.innerHTML = result.retrieved_chunks.map((chunk) => `
      <article class="evidence-card">
        <div>
          <strong>${escapeHtml(chunk.heading)}</strong>
          <small>${escapeHtml(chunk.source)} | score ${chunk.score}</small>
        </div>
        <p>${escapeHtml(chunk.preview)}</p>
      </article>
    `).join("");
  } catch (error) {
    answerEl.innerHTML = `<p>Unable to run the assistant right now. Check that the API server is running.</p>`;
  }
}

function renderAssistantAnswer(result, modeLabel) {
  const meta = `
    <div class="answer-meta">
      <span class="pill ${result.llm_available ? "success" : "warning"}">${modeLabel}</span>
      <span>${result.citations.length} citation${result.citations.length === 1 ? "" : "s"}</span>
    </div>
  `;

  if (result.mode === "fx-outlook" && result.metrics) {
    const metrics = result.metrics;
    const direction = metrics.direction === "up" ? "up" : metrics.direction === "down" ? "down" : "flat";
    const arrow = direction === "up" ? "&uarr;" : direction === "down" ? "&darr;" : "&bull;";
    return `
      ${meta}
      <div class="outlook-card">
        <div>
          <span class="eyebrow">Trend-based outlook</span>
          <h3>${escapeHtml(metrics.pair)}</h3>
        </div>
        <div class="outlook-grid">
          <div><span>Latest</span><strong>${escapeHtml(metrics.latest_rate)}</strong><small>${escapeHtml(metrics.latest_date)}</small></div>
          <div><span>${escapeHtml(metrics.average_days)}-day avg</span><strong>${escapeHtml(metrics.average_rate)}</strong><small>comparison baseline</small></div>
          <div><span>30-day move</span><strong class="${direction}"><span class="trend-arrow ${direction}">${arrow}</span>${escapeHtml(metrics.change_percent)}%</strong><small>from ${escapeHtml(metrics.start_rate)}</small></div>
          <div><span>Signal</span><strong>${escapeHtml(metrics.bias)}</strong><small>not a prediction</small></div>
        </div>
      </div>
      <p>${escapeHtml(result.answer).replace(/\n/g, "<br>")}</p>
    `;
  }

  return `${meta}<p>${escapeHtml(result.answer).replace(/\n/g, "<br>")}</p>`;
}

async function convert() {
  const payload = {
    amount: Number(document.querySelector("#amount").value),
    from_currency: document.querySelector("#from-currency").value,
    to_currency: document.querySelector("#to-currency").value,
  };
  const result = await request("/api/fx/convert", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  document.querySelector("#conversion-result").textContent = `${payload.amount.toLocaleString()} ${result.from_currency} = ${result.converted_amount.toLocaleString()} ${result.to_currency}`;
  document.querySelector("#unit-rate").textContent = `1 ${result.from_currency} = ${result.rate.toLocaleString()} ${result.to_currency}`;
  document.querySelector("#fx-source").textContent = `${result.is_live ? "Live" : "Demo"} rate from ${result.provider}; as of ${result.as_of}.`;
}

async function previewTransferConversion() {
  const output = document.querySelector("#transfer-preview");
  const amount = Number(document.querySelector("#transfer-amount").value);
  const fromCurrency = document.querySelector("#transfer-from").value;
  const toCurrency = document.querySelector("#transfer-to").value;

  if (!amount || amount <= 0) {
    output.textContent = "Enter transfer details to preview conversion.";
    return;
  }

  output.textContent = "Calculating live conversion...";
  try {
    const result = await request("/api/fx/convert", {
      method: "POST",
      body: JSON.stringify({
        amount,
        from_currency: fromCurrency,
        to_currency: toCurrency,
      }),
    });

    output.innerHTML = `
      <strong>${amount.toLocaleString()} ${escapeHtml(result.from_currency)} = ${result.converted_amount.toLocaleString()} ${escapeHtml(result.to_currency)}</strong>
      <span>1 ${escapeHtml(result.from_currency)} = ${result.rate.toLocaleString()} ${escapeHtml(result.to_currency)} &middot; ${escapeHtml(result.provider)}</span>
    `;
  } catch (error) {
    output.textContent = "Unable to preview conversion right now.";
  }
}

async function loadReport() {
  const output = document.querySelector("#report-output");
  output.textContent = "Generating report...";
  const result = await request("/api/reports/daily");
  output.textContent = renderJson(result);
}

async function submitTransfer(event) {
  event.preventDefault();
  const output = document.querySelector("#transfer-result");
  output.innerHTML = `<div class="loading-line"></div><p>Submitting transfer and saving SQL record...</p>`;

  const payload = {
    customer_name: document.querySelector("#transfer-customer").value,
    amount: Number(document.querySelector("#transfer-amount").value),
    from_currency: document.querySelector("#transfer-from").value,
    to_currency: document.querySelector("#transfer-to").value,
    beneficiary_country: document.querySelector("#transfer-country").value,
    purpose: document.querySelector("#transfer-purpose").value,
  };

  const result = await request("/api/transfers", {
    method: "POST",
    body: JSON.stringify(payload),
  });

  if (!result.stored) {
    const status = result.database_status || {};
    output.innerHTML = `
      <div class="answer-meta"><span class="pill warning">Not saved</span></div>
      <p>Supabase/database is not available, so the transfer was not stored.</p>
      <p>${escapeHtml(status.next_steps?.join(" ") || status.error || "Check DATABASE_URL and restart the API.")}</p>
    `;
    await loadDatabaseStatus();
    return;
  }

  const transfer = result.transfer;
  output.innerHTML = `
    <div class="answer-meta"><span class="pill success">Saved</span><span>${transfer.transfer_id}</span></div>
    <p>${transfer.amount.toLocaleString()} ${transfer.from_currency} = ${transfer.converted_amount.toLocaleString()} ${transfer.to_currency}</p>
    <p>1 ${transfer.from_currency} = ${transfer.rate.toLocaleString()} ${transfer.to_currency}. Stored in ${result.database_status.provider}.</p>
  `;
  await loadDatabaseStatus();
  await loadSummary();
}

function openAdminLogin(event) {
  event?.preventDefault();
  const modal = document.querySelector("#admin-login-modal");
  const error = document.querySelector("#admin-login-error");
  document.querySelector("#admin-username").value = demoAdminCredentials.username;
  document.querySelector("#admin-password").value = demoAdminCredentials.password;
  error.classList.add("hidden");
  modal.classList.remove("hidden");
  document.querySelector("#admin-username").focus();
}

function closeAdminLogin() {
  document.querySelector("#admin-login-modal").classList.add("hidden");
}

function submitAdminLogin(event) {
  event.preventDefault();
  const username = document.querySelector("#admin-username").value.trim();
  const password = document.querySelector("#admin-password").value;
  const error = document.querySelector("#admin-login-error");

  if (username === demoAdminCredentials.username && password === demoAdminCredentials.password) {
    sessionStorage.setItem("finfxAdminSession", "active");
    window.location.href = "/reports.html";
    return;
  }

  error.classList.remove("hidden");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

document.querySelector("#ask-knowledge").addEventListener("click", askKnowledge);
document.querySelector("#convert").addEventListener("click", convert);
document.querySelector("#transfer-form").addEventListener("submit", submitTransfer);
document.querySelector("#refresh-llm-usage").addEventListener("click", loadLlmUsage);
document.querySelector("#admin-reports-link").addEventListener("click", openAdminLogin);
document.querySelector("#admin-login-close").addEventListener("click", closeAdminLogin);
document.querySelector("#admin-login-form").addEventListener("submit", submitAdminLogin);
document.querySelector("#admin-login-modal").addEventListener("click", (event) => {
  if (event.target.id === "admin-login-modal") closeAdminLogin();
});
["#transfer-amount", "#transfer-from", "#transfer-to"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", previewTransferConversion);
  document.querySelector(selector).addEventListener("change", previewTransferConversion);
});

document.querySelectorAll("[data-question]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#knowledge-question").value = button.dataset.question;
    askKnowledge();
  });
});

document.querySelectorAll("[data-rate-group]").forEach((button) => {
  button.addEventListener("click", () => {
    selectedRateGroup = button.dataset.rateGroup;
    document.querySelectorAll("[data-rate-group]").forEach((tab) => tab.classList.remove("active"));
    button.classList.add("active");
    renderLiveRates();
  });
});

loadSummary();
loadDatabaseStatus();
loadLiveRates();
loadProviders();
loadLlmUsage();
convert();
previewTransferConversion();
if (window.location.hash === "#admin-login-required") {
  openAdminLogin();
}

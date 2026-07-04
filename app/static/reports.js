async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

if (sessionStorage.getItem("finfxAdminSession") !== "active") {
  window.location.replace("/#admin-login-required");
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

let allTransfers = [];
let llmUsage = null;
let questionUsage = null;

async function loadReportsPage() {
  const [status, transfers, usage, questions] = await Promise.all([
    request("/api/database/status"),
    request("/api/transfers?limit=500"),
    request("/api/llm/usage/persisted"),
    request("/api/assistant/questions/persisted"),
  ]);

  renderDatabaseStatus(status);
  allTransfers = transfers.transfers || [];
  llmUsage = usage;
  questionUsage = questions;
  populateCurrencyFilter(allTransfers);
  renderDashboard();
  renderLlmUsageDashboard(llmUsage);
  renderQuestionUsageDashboard(questionUsage);
}

async function askSql() {
  const question = document.querySelector("#sql-question").value.trim();
  const output = document.querySelector("#sql-answer");
  const resultView = document.querySelector("#sql-result-view");

  if (!question) {
    output.textContent = "Type a Supabase transfer question first.";
    resultView.innerHTML = "";
    return;
  }

  output.textContent = "Running Supabase SQL analytics...";
  resultView.innerHTML = "";
  try {
    const result = await request("/api/sql/ask", {
      method: "POST",
      body: JSON.stringify({ question }),
    });
    const sql = result.safe_sql || result.generated_sql || "No SQL was executed.";
    const schemaSource = result.schema_context?.[0]?.source ? `\nSchema source: ${result.schema_context[0].source}` : "";
    output.textContent = `Mode: ${result.mode || "template"}${schemaSource}\n${result.explanation}\n\n${sql}`;
    renderSqlResult(result);
  } catch (error) {
    output.textContent = "Unable to run SQL analytics. Check that the API server and Supabase connection are available.";
    resultView.innerHTML = "";
  }
}

function renderDatabaseStatus(status) {
  const pill = document.querySelector("#reports-database-pill");
  const alert = document.querySelector("#reports-db-alert");

  if (status.available) {
    pill.textContent = `${status.provider} active`;
    pill.className = "pill success";
    alert.classList.add("hidden");
    return;
  }

  pill.textContent = `${status.provider} unavailable`;
  pill.className = "pill warning";
  alert.classList.remove("hidden");
  alert.innerHTML = `
    <strong>Supabase/database is not available.</strong>
    <span>${escapeHtml(status.next_steps?.join(" ") || status.error || "Check DATABASE_URL and restart the API.")}</span>
  `;
}

function populateCurrencyFilter(transfers) {
  const select = document.querySelector("#filter-from-currency");
  const existingValue = select.value || "ALL";
  const currencies = [...new Set(transfers.map((transfer) => transfer.from_currency).filter(Boolean))].sort();
  select.innerHTML = `<option value="ALL">All currencies</option>${currencies.map((currency) => (
    `<option value="${escapeHtml(currency)}">${escapeHtml(currency)}</option>`
  )).join("")}`;
  select.value = currencies.includes(existingValue) ? existingValue : "ALL";
}

function renderDashboard() {
  const filtered = filteredTransfers();
  renderReportKpis(filtered);
  renderCurrencyMatrix(filtered);
  renderCorridorChart(filtered);
  renderTransfers(filtered.slice(0, 50));
}

function filteredTransfers() {
  const fromCurrency = document.querySelector("#filter-from-currency").value;
  const period = document.querySelector("#filter-period").value;
  const now = new Date();

  return allTransfers.filter((transfer) => {
    if (fromCurrency !== "ALL" && transfer.from_currency !== fromCurrency) return false;

    const createdAt = new Date(transfer.created_at);
    if (Number.isNaN(createdAt.getTime())) return period === "all";

    if (period === "today") {
      return createdAt.toISOString().slice(0, 10) === now.toISOString().slice(0, 10);
    }
    if (period === "7d") {
      return createdAt >= new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    }
    if (period === "30d") {
      return createdAt >= new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    }

    return true;
  });
}

function renderReportKpis(transfers) {
  const totalSource = transfers.reduce((sum, transfer) => sum + Number(transfer.amount || 0), 0);
  const averageRate = transfers.length
    ? transfers.reduce((sum, transfer) => sum + Number(transfer.rate || 0), 0) / transfers.length
    : null;
  const targetTotals = groupByCurrency(transfers, "to_currency", "amount");
  const topTarget = Object.entries(targetTotals).sort((a, b) => b[1] - a[1])[0];

  document.querySelector("#report-total-count").textContent = transfers.length.toLocaleString();
  document.querySelector("#report-total-source").textContent = compactNumber(totalSource);
  document.querySelector("#report-top-target").textContent = topTarget ? `${topTarget[0]} ${compactNumber(topTarget[1])}` : "n/a";
  document.querySelector("#report-average-rate").textContent = averageRate ? averageRate.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "n/a";
}

function renderCurrencyMatrix(transfers) {
  const container = document.querySelector("#currency-matrix");
  if (!transfers.length) {
    container.innerHTML = `<p class="empty-state">No transfers match the selected filters.</p>`;
    return;
  }

  const fromCurrencies = [...new Set(transfers.map((transfer) => transfer.from_currency))].sort();
  const toCurrencies = [...new Set(transfers.map((transfer) => transfer.to_currency))].sort();
  const matrix = {};

  transfers.forEach((transfer) => {
    matrix[transfer.from_currency] ||= {};
    matrix[transfer.from_currency][transfer.to_currency] ||= { count: 0, amount: 0 };
    matrix[transfer.from_currency][transfer.to_currency].count += 1;
    matrix[transfer.from_currency][transfer.to_currency].amount += Number(transfer.amount || 0);
  });

  container.innerHTML = `
    <table class="rates-table matrix-table">
      <thead>
        <tr>
          <th>From currency</th>
          ${toCurrencies.map((currency) => `<th>${escapeHtml(currency)}</th>`).join("")}
        </tr>
      </thead>
      <tbody>
        ${fromCurrencies.map((fromCurrency) => {
          const totalCount = Object.values(matrix[fromCurrency] || {}).reduce((sum, cell) => sum + cell.count, 0);
          return `
            <tr>
              <td><strong>${escapeHtml(fromCurrency)} (${totalCount})</strong></td>
              ${toCurrencies.map((toCurrency) => {
                const cell = matrix[fromCurrency]?.[toCurrency] || { count: 0, amount: 0 };
                return `<td><strong>${cell.count}</strong><small>${compactNumber(cell.amount)} sent</small></td>`;
              }).join("")}
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}

function renderCorridorChart(transfers) {
  const chart = document.querySelector("#corridor-chart");
  const metric = document.querySelector("#filter-metric").value;
  const fromCurrency = document.querySelector("#filter-from-currency").value;
  const grouped = groupByCurrency(transfers, "to_currency", metric);
  const entries = Object.entries(grouped).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map((entry) => entry[1]), 0);

  document.querySelector("#corridor-chart-title").textContent = fromCurrency === "ALL"
    ? "Transfers by target currency"
    : `${fromCurrency} transfers by target currency`;

  if (!entries.length || max === 0) {
    chart.innerHTML = `<p class="empty-state">No chart data for the selected filters.</p>`;
    return;
  }

  chart.innerHTML = entries.map(([currency, value]) => `
    <div class="chart-row">
      <span>${escapeHtml(currency)}</span>
      <div class="chart-track">
        <div class="chart-fill" style="width: ${Math.max((value / max) * 100, 3)}%"></div>
      </div>
      <strong>${metric === "count" ? value.toLocaleString() : compactNumber(value)}</strong>
    </div>
  `).join("");
}

function groupByCurrency(transfers, currencyKey, metric) {
  return transfers.reduce((groups, transfer) => {
    const currency = transfer[currencyKey] || "Unknown";
    const value = metric === "count" ? 1 : Number(transfer[metric] || 0);
    groups[currency] = (groups[currency] || 0) + value;
    return groups;
  }, {});
}

function compactNumber(value) {
  return Number(value || 0).toLocaleString(undefined, {
    maximumFractionDigits: value >= 1000 ? 0 : 2,
  });
}

function renderTransfers(transfers) {
  const body = document.querySelector("#transfer-table-body");
  if (!transfers.length) {
    body.innerHTML = `<tr><td colspan="5">No matching transfer records.</td></tr>`;
    return;
  }

  body.innerHTML = transfers.map((transfer) => `
    <tr>
      <td><strong>${escapeHtml(transfer.transfer_id)}</strong><small>${escapeHtml(transfer.created_at)}</small></td>
      <td>${escapeHtml(transfer.customer_name)}<small>${escapeHtml(transfer.beneficiary_country)}</small></td>
      <td>${transfer.amount.toLocaleString()} ${escapeHtml(transfer.from_currency)}</td>
      <td>${transfer.converted_amount.toLocaleString()} ${escapeHtml(transfer.to_currency)}<small>rate ${transfer.rate}</small></td>
      <td><span class="pill success">${escapeHtml(transfer.status)}</span></td>
    </tr>
  `).join("");
}

function renderSqlResult(result) {
  const resultView = document.querySelector("#sql-result-view");

  if (result.mode === "llm-sql-blocked") {
    resultView.innerHTML = `<div class="db-alert inline-alert"><strong>Blocked unsafe SQL.</strong><span>${escapeHtml(result.explanation)}</span></div>`;
    return;
  }

  if (Array.isArray(result.result)) {
    if (!result.result.length) {
      resultView.innerHTML = `<p class="source-note">No matching Supabase transfer records.</p>`;
      return;
    }

    const columns = Object.keys(result.result[0]);
    resultView.innerHTML = `
      <div class="table-wrap">
        <table class="rates-table">
          <thead>
            <tr>${columns.map((column) => `<th>${escapeHtml(column.replaceAll("_", " "))}</th>`).join("")}</tr>
          </thead>
          <tbody>
            ${result.result.map((row) => `
              <tr>${columns.map((column) => `<td>${escapeHtml(row[column])}</td>`).join("")}</tr>
            `).join("")}
          </tbody>
        </table>
      </div>
    `;
    return;
  }

  if (result.result && typeof result.result === "object") {
    resultView.innerHTML = `
      <div class="summary-grid">
        ${Object.entries(result.result).map(([key, value]) => `
          <article class="summary-card">
            <span>${escapeHtml(key.replaceAll("_", " "))}</span>
            <strong>${escapeHtml(value)}</strong>
          </article>
        `).join("")}
      </div>
    `;
    return;
  }

  resultView.innerHTML = `<p class="source-note">No result returned.</p>`;
}

function renderLlmUsageDashboard(usage) {
  const status = usage.database_status || {};
  const totals = usage.totals || {};
  const providerEntries = Object.entries(usage.by_provider || {}).sort((a, b) => b[1].total_tokens - a[1].total_tokens);
  const topProvider = providerEntries[0];
  const pill = document.querySelector("#llm-log-pill");

  pill.textContent = status.available ? "Supabase logs active" : "Logs unavailable";
  pill.className = status.available ? "pill success" : "pill warning";
  document.querySelector("#llm-total-calls").textContent = Number(totals.calls || 0).toLocaleString();
  document.querySelector("#llm-total-tokens").textContent = Number(totals.total_tokens || 0).toLocaleString();
  document.querySelector("#llm-top-provider").textContent = topProvider ? topProvider[0] : "n/a";
  document.querySelector("#llm-failed-calls").textContent = Number(totals.failed_calls || 0).toLocaleString();

  renderUsageChart("#llm-provider-chart", usage.by_provider || {}, "total_tokens");
  renderUsageChart("#llm-calltype-chart", usage.by_call_type || {}, "calls");
  renderLlmUsageTable(usage.recent || []);
}

function renderUsageChart(selector, groups, metric) {
  const chart = document.querySelector(selector);
  const entries = Object.entries(groups).sort((a, b) => b[1][metric] - a[1][metric]);
  const max = Math.max(...entries.map((entry) => entry[1][metric]), 0);
  if (!entries.length || max === 0) {
    chart.innerHTML = `<p class="empty-state">No persisted LLM usage yet.</p>`;
    return;
  }

  chart.innerHTML = entries.map(([label, row]) => `
    <div class="chart-row">
      <span>${escapeHtml(label)}</span>
      <div class="chart-track">
        <div class="chart-fill" style="width: ${Math.max((row[metric] / max) * 100, 3)}%"></div>
      </div>
      <strong>${Number(row[metric] || 0).toLocaleString()}</strong>
    </div>
  `).join("");
}

function renderLlmUsageTable(logs) {
  const body = document.querySelector("#llm-log-table-body");
  if (!logs.length) {
    body.innerHTML = `<tr><td colspan="6">No persisted LLM usage logs yet.</td></tr>`;
    return;
  }

  body.innerHTML = logs.map((log) => `
    <tr>
      <td><strong>${escapeHtml(formatDateTime(log.created_at))}</strong><small>${escapeHtml(log.usage_id)}</small></td>
      <td>${escapeHtml(log.provider)}</td>
      <td>${escapeHtml(log.model)}</td>
      <td>${escapeHtml(log.call_type)}</td>
      <td>${Number(log.total_tokens || 0).toLocaleString()}<small>${Number(log.input_tokens || 0).toLocaleString()} in / ${Number(log.output_tokens || 0).toLocaleString()} out${log.question_id ? ` / ${escapeHtml(log.question_id)}` : ""}</small></td>
      <td><span class="pill ${log.success ? "success" : "warning"}">${log.success ? "success" : "failed"}</span></td>
    </tr>
  `).join("");
}

function renderQuestionUsageDashboard(usage) {
  const status = usage.database_status || {};
  const totals = usage.totals || {};
  const pill = document.querySelector("#question-log-pill");

  pill.textContent = status.available ? "Question logs active" : "Questions unavailable";
  pill.className = status.available ? "pill success" : "pill warning";
  document.querySelector("#question-total-count").textContent = Number(totals.questions || 0).toLocaleString();
  document.querySelector("#question-llm-calls").textContent = Number(totals.llm_calls || 0).toLocaleString();
  document.querySelector("#question-total-tokens").textContent = Number(totals.total_tokens || 0).toLocaleString();
  document.querySelector("#question-average-latency").textContent = `${Number(totals.average_latency_ms || 0).toLocaleString()} ms`;
  renderQuestionUsageTable(usage.recent || []);
}

function renderQuestionUsageTable(questions) {
  const body = document.querySelector("#question-log-table-body");
  if (!questions.length) {
    body.innerHTML = `<tr><td colspan="5">No assistant question logs yet.</td></tr>`;
    return;
  }

  body.innerHTML = questions.map((question) => `
    <tr>
      <td><strong>${escapeHtml(question.question_text)}</strong><small>${escapeHtml(question.question_id)} · ${escapeHtml(formatDateTime(question.created_at))}</small></td>
      <td>${escapeHtml(question.surface)}</td>
      <td>${escapeHtml(question.route_mode || "unknown")}<small>${escapeHtml(question.intent || "no intent")}</small></td>
      <td>${Number(question.total_tokens || 0).toLocaleString()} tokens<small>${Number(question.llm_calls || 0).toLocaleString()} calls · ${Number(question.latency_ms || 0).toLocaleString()} ms</small></td>
      <td><span class="pill ${question.status === "success" ? "success" : "warning"}">${escapeHtml(question.status)}</span></td>
    </tr>
  `).join("");
}

function showReportPage(page) {
  const selectedPage = page === "observability" ? "observability" : "dashboard";
  document.querySelectorAll(".report-page").forEach((section) => {
    section.classList.toggle("active", section.id === `report-page-${selectedPage}`);
  });
  document.querySelectorAll("[data-report-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.reportPage === selectedPage);
  });
  const url = new URL(window.location.href);
  url.searchParams.set("page", selectedPage);
  window.history.replaceState({}, "", url);
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

document.querySelector("#refresh-reports").addEventListener("click", loadReportsPage);
document.querySelector("#filter-from-currency").addEventListener("change", renderDashboard);
document.querySelector("#filter-period").addEventListener("change", renderDashboard);
document.querySelector("#filter-metric").addEventListener("change", renderDashboard);
document.querySelector("#ask-sql").addEventListener("click", askSql);
document.querySelectorAll("[data-report-page]").forEach((button) => {
  button.addEventListener("click", () => showReportPage(button.dataset.reportPage));
});
document.querySelectorAll("[data-sql-question]").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelector("#sql-question").value = button.dataset.sqlQuestion;
    askSql();
  });
});
showReportPage(new URLSearchParams(window.location.search).get("page"));
loadReportsPage();

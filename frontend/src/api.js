const BASE = "/api";
export const getToken = () => localStorage.getItem("dp_token");
export const setToken = (t) => (t ? localStorage.setItem("dp_token", t) : localStorage.removeItem("dp_token"));

async function request(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (getToken()) headers.Authorization = `Bearer ${getToken()}`;
  const res = await fetch(BASE + path, { ...opts, headers });
  if (res.status === 401 && getToken()) {
    setToken(null);
    window.location.reload();
  }
  if (!res.ok) {
    let msg = res.statusText || "Request failed";
    try {
      const j = await res.json();
      if (typeof j.detail === "string") {
        msg = j.detail;
      } else if (Array.isArray(j.detail)) {
        msg = j.detail.map((d) => d.msg || JSON.stringify(d)).join(", ");
      } else if (j.detail) {
        msg = JSON.stringify(j.detail);
      }
    } catch {}
    if (res.status >= 500 && msg === "Internal Server Error") {
      msg = "Server unavailable or internal error. Please ensure the backend server is active.";
    }
    throw new Error(msg);
  }
  return res;
}

export async function api(path, { method = "GET", body } = {}) {
  const res = await request(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  return res.json();
}

api.listDatasets = () => api("/datasets");
api.getDataset = (id) => api(`/datasets/${id}`);
api.deleteDataset = (id) => api(`/datasets/${id}`, { method: "DELETE" });

export async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  return (await request("/data-cleaning/upload", { method: "POST", body: fd })).json();
}

export async function uploadWithConfig(file, { sheetName = null, nullMarkers = null } = {}) {
  const fd = new FormData();
  fd.append("file", file);
  if (sheetName) fd.append("sheet_name", sheetName);
  if (nullMarkers) fd.append("null_markers", nullMarkers);
  return (await request("/data-cleaning/upload", { method: "POST", body: fd })).json();
}

export async function inspectExcelSheets(file) {
  const fd = new FormData();
  fd.append("file", file);
  return (await request("/data-cleaning/inspect-sheets", { method: "POST", body: fd })).json();
}

export async function loadSample(sampleName = "sales.csv") {
  return api(`/data-cleaning/load-sample?sample_name=${encodeURIComponent(sampleName)}`, { method: "POST" });
}

export async function downloadFile(path, fallbackFilename, opts = {}) {
  const fetchOpts = { ...opts };
  if (fetchOpts.body && typeof fetchOpts.body === "object" && !(fetchOpts.body instanceof FormData)) {
    fetchOpts.headers = {
      "Content-Type": "application/json",
      ...(fetchOpts.headers || {}),
    };
    fetchOpts.body = JSON.stringify(fetchOpts.body);
  }
  const res = await request(path, fetchOpts);
  const blob = await res.blob();
  const disposition = res.headers.get("content-disposition") || "";
  let filename = fallbackFilename;
  const match = disposition.match(/filename\*?=(?:UTF-8'')?["']?([^"';]+)["']?/i);
  if (match && match[1]) {
    filename = decodeURIComponent(match[1]);
  }
  // Test that downloaded bytes start with zip magic "PK" if .xlsx
  if (filename.toLowerCase().endsWith(".xlsx")) {
    const slice = await blob.slice(0, 2).arrayBuffer();
    const bytes = new Uint8Array(slice);
    const isZip = bytes.length >= 2 && bytes[0] === 0x50 && bytes[1] === 0x4B; // 'P', 'K'
    if (!isZip) {
      console.warn("Downloaded .xlsx file does NOT start with zip magic PK header!");
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  return { filename, size: blob.size };
}

export async function downloadReport(body) {
  const res = await request("/reports/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = "datapilot_report.html";
  a.click();
  URL.revokeObjectURL(url);
}

// ── Multi-Source Connectors ───────────────────────────────────────────
api.listConnections = () => api("/connectors");
api.createConnection = (data) => api("/connectors", { method: "POST", body: data });
api.getConnection = (id) => api(`/connectors/${id}`);
api.updateConnection = (id, data) => api(`/connectors/${id}`, { method: "PUT", body: data });
api.deleteConnection = (id) => api(`/connectors/${id}`, { method: "DELETE" });
api.testConnection = (id) => api(`/connectors/${id}/test`, { method: "POST" });
api.browseSchema = (id) => api(`/connectors/${id}/schema`);
api.pullData = (id, data) => api(`/connectors/${id}/pull`, { method: "POST", body: data });
api.getPullHistory = (id) => api(`/connectors/${id}/history`);

// ── Quality Scorecard & Rules ─────────────────────────────────────────
api.getQualityScorecard = (datasetId) => api(`/quality/scorecard/${datasetId}`);
api.listQualityRules = (datasetId) => api(`/quality/rules/${datasetId}`);
api.createQualityRule = (datasetId, rule) => api(`/quality/rules/${datasetId}`, { method: "POST", body: rule });
api.deleteQualityRule = (datasetId, ruleId) => api(`/quality/rules/${datasetId}/${ruleId}`, { method: "DELETE" });
api.exportQualityHtml = (datasetId) => downloadFile(`/quality/export/${datasetId}/html`, `${datasetId}_quality_report.html`);
api.exportQualityExcel = (datasetId) => downloadFile(`/quality/export/${datasetId}/excel`, `${datasetId}_quality_report.xlsx`);

// ── Data Modelling ────────────────────────────────────────────────────
api.listModels = () => api("/modelling/models");
api.createModel = (data) => api("/modelling/models", { method: "POST", body: data });
api.getModel = (id) => api(`/modelling/models/${id}`);
api.updateModel = (id, data) => api(`/modelling/models/${id}`, { method: "PUT", body: data });
api.deleteModel = (id) => api(`/modelling/models/${id}`, { method: "DELETE" });
api.detectKeys = (datasetId) => api(`/modelling/detect-keys/${datasetId}`, { method: "POST" });
api.detectRelationships = (datasetIds) => api("/modelling/detect-relationships", { method: "POST", body: { dataset_ids: datasetIds } });
api.validateRelationship = (data) => api("/modelling/validate-relationship", { method: "POST", body: data });
api.generateDateDimension = (data) => api("/modelling/generate-date-dimension", { method: "POST", body: data });
api.getSemanticLayer = (modelId) => api(`/modelling/models/${modelId}/semantic-layer`);
api.saveSemanticLayer = (modelId, data) => api(`/modelling/models/${modelId}/semantic-layer`, { method: "PUT", body: data });

// ── ETL Pipelines ─────────────────────────────────────────────────────
api.listPipelines = () => api("/pipelines");
api.createPipeline = (data) => api("/pipelines", { method: "POST", body: data });
api.getPipeline = (id) => api(`/pipelines/${id}`);
api.updatePipeline = (id, data) => api(`/pipelines/${id}`, { method: "PUT", body: data });
api.deletePipeline = (id) => api(`/pipelines/${id}`, { method: "DELETE" });
api.runPipeline = (id, params) => api(`/pipelines/${id}/run`, { method: "POST", body: { parameters: params || {} } });
api.listPipelineRuns = (id) => api(`/pipelines/${id}/runs`);
api.getPipelineCode = async (id, lang) => {
  const res = await request(`/pipelines/${id}/code/${lang}`);
  return res.text();
};

// ── Domain KPI Catalogue ──────────────────────────────────────────────
api.listKpiDomains = () => api("/kpis/domains");
api.detectKpis = (datasetId) => api(`/kpis/detect/${datasetId}`);
api.computeKpis = (datasetId, data) => api(`/kpis/compute/${datasetId}`, { method: "POST", body: data });

// ── Requirements Workspace (Projects) ─────────────────────────────────
api.listProjects = () => api("/projects");
api.getActiveProject = () => api("/projects/active");
api.createProject = (data) => api("/projects", { method: "POST", body: data });
api.getProject = (id) => api(`/projects/${id}`);
api.updateProject = (id, data) => api(`/projects/${id}`, { method: "PUT", body: data });
api.deleteProject = (id) => api(`/projects/${id}`, { method: "DELETE" });
api.activateProject = (id) => api(`/projects/${id}/activate`, { method: "POST" });
api.linkProjectDataset = (id, datasetId, version = 1) => api(`/projects/${id}/dataset`, { method: "POST", body: { dataset_id: datasetId, version } });
api.addProjectActivity = (id, action, details) => api(`/projects/${id}/activity`, { method: "POST", body: { action, details } });
api.generateAnalysisPlan = (data) => api("/projects/generate-plan", { method: "POST", body: data });

// ── Documentation & Presentations ─────────────────────────────────────
api.getDataDictionary = (datasetId) => api(`/documentation/data-dictionary/${datasetId}`);
api.getProcessDoc = (datasetId) => api(`/documentation/process-doc/${datasetId}`);
api.getStakeholderSummary = (datasetId) => api(`/documentation/stakeholder-summary/${datasetId}`);
api.downloadDeck = (datasetId, body, name = "presentation") => downloadFile(`/documentation/deck/${datasetId}`, `${name}_insights.pptx`, { method: "POST", body });

// ── Interactive Spreadsheet & Grid Engine ─────────────────────────────
api.updateCell = (dsId, data) => api(`/data-cleaning/${dsId}/update-cell`, { method: "POST", body: data });
api.imputeColumn = (dsId, data) => api(`/data-cleaning/${dsId}/impute-column`, { method: "POST", body: data });
api.getImputationSuggestions = (dsId) => api(`/data-cleaning/${dsId}/imputation-suggestions`);
api.getGrid = (dsId, { sheet, offset = 0, limit = 50, view = "cleaned", search, sortBy, sortAsc = true, issueFilter, columnFilter } = {}) => {
  const p = new URLSearchParams({ offset: String(offset), limit: String(limit), view });
  if (sheet) p.set("sheet", sheet);
  if (search) p.set("search", search);
  if (sortBy) {
    p.set("sort_by", sortBy);
    p.set("sort_asc", String(sortAsc));
  }
  if (issueFilter) p.set("issue_filter", issueFilter);
  if (columnFilter) p.set("column_filter", columnFilter);
  return api(`/datasets/${dsId}/grid?${p.toString()}`);
};
api.getIssues = (dsId) => api(`/datasets/${dsId}/issues`);
api.getSuggest = (dsId, col, issue = "missing", row = 0) =>
  api(`/datasets/${dsId}/suggest?column=${encodeURIComponent(col)}&issue=${encodeURIComponent(issue)}&row=${row}`);
api.applyFix = (dsId, data) => api(`/datasets/${dsId}/fix`, { method: "POST", body: data });
api.batchUpdateCells = (dsId, edits) => api(`/datasets/${dsId}/cells`, { method: "PATCH", body: { edits } });
api.undoGrid = (dsId) => api(`/datasets/${dsId}/undo`, { method: "POST" });
api.redoGrid = (dsId) => api(`/datasets/${dsId}/redo`, { method: "POST" });
api.revertCell = (dsId, row, column) => api(`/datasets/${dsId}/revert-cell`, { method: "POST", body: { row, column } });
api.fixAllSuggested = (dsId) => api(`/datasets/${dsId}/fix-all-suggested`, { method: "POST" });
api.getCleanCheck = (dsId) => api(`/datasets/${dsId}/clean-check`);
api.columnAction = (dsId, data) => api(`/datasets/${dsId}/column-action`, { method: "POST", body: data });

api.getDashboardData = (dsId, filters = {}) => {
  const p = new URLSearchParams();
  if (filters.date_min) p.set("date_min", filters.date_min);
  if (filters.date_max) p.set("date_max", filters.date_max);
  if (filters.date_grain) p.set("date_grain", filters.date_grain);
  if (filters.cat1_col && filters.cat1_vals) {
    p.set("cat1_col", filters.cat1_col);
    p.set("cat1_vals", Array.isArray(filters.cat1_vals) ? filters.cat1_vals.join(",") : filters.cat1_vals);
  }
  if (filters.cat2_col && filters.cat2_vals) {
    p.set("cat2_col", filters.cat2_col);
    p.set("cat2_vals", Array.isArray(filters.cat2_vals) ? filters.cat2_vals.join(",") : filters.cat2_vals);
  }
  if (filters.cat3_col && filters.cat3_vals) {
    p.set("cat3_col", filters.cat3_col);
    p.set("cat3_vals", Array.isArray(filters.cat3_vals) ? filters.cat3_vals.join(",") : filters.cat3_vals);
  }
  if (filters.cross_dim && filters.cross_val) {
    p.set("cross_dim", filters.cross_dim);
    p.set("cross_val", Array.isArray(filters.cross_val) ? filters.cross_val.join(",") : filters.cross_val);
  }
  return api(`/datasets/${dsId}/dashboard-data?${p.toString()}`);
};

api.downloadReportPdf = async (dsId, filters = {}, filename = "report.pdf") => {
  const p = new URLSearchParams();
  if (filters.date_min) p.set("date_min", filters.date_min);
  if (filters.date_max) p.set("date_max", filters.date_max);
  if (filters.cat1_col && filters.cat1_vals) {
    p.set("cat1_col", filters.cat1_col);
    p.set("cat1_vals", Array.isArray(filters.cat1_vals) ? filters.cat1_vals.join(",") : filters.cat1_vals);
  }
  if (filters.cat2_col && filters.cat2_vals) {
    p.set("cat2_col", filters.cat2_col);
    p.set("cat2_vals", Array.isArray(filters.cat2_vals) ? filters.cat2_vals.join(",") : filters.cat2_vals);
  }
  if (filters.cat3_col && filters.cat3_vals) {
    p.set("cat3_col", filters.cat3_col);
    p.set("cat3_vals", Array.isArray(filters.cat3_vals) ? filters.cat3_vals.join(",") : filters.cat3_vals);
  }
  if (filters.cross_dim && filters.cross_val) {
    p.set("cross_dim", filters.cross_dim);
    p.set("cross_val", Array.isArray(filters.cross_val) ? filters.cross_val.join(",") : filters.cross_val);
  }
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`/api/datasets/${dsId}/download-report?${p.toString()}`, { headers });
  if (!res.ok) throw new Error("Failed to download PDF report");
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
};




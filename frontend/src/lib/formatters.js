/**
 * Consistent formatting module for DataPilot (KPIs, Tables, Visuals, Tooltips, Axes).
 * Synchronized with backend services/formatters.py.
 * Supports:
 * - Indian lakh/crore formatting (12.5L, 3.2Cr) for rupee metrics.
 * - Standard compact formatting (K, M, B) for others.
 * - Percentage and date grain formatting.
 * - Tabular numbers and label truncation (24 characters with '...').
 */

export function isNumeric(val) {
  if (val === null || val === undefined || val === "") return false;
  return !isNaN(Number(val));
}

export function isIndianCurrency(curr) {
  if (!curr) return false;
  const s = String(curr).toLowerCase();
  return s.includes("inr") || s.includes("₹") || s.includes("rupee") || s.includes("rs") || s.includes("lakh") || s.includes("crore");
}

export function formatCompactNumber(val, { currency = null, decimals = 1, forceIndian = null } = {}) {
  if (val === null || val === undefined || val === "") return "—";
  const num = Number(val);
  if (isNaN(num)) return String(val);

  let prefix = "";
  if (currency) {
    const cLower = String(currency).toLowerCase();
    if (cLower.includes("usd") || cLower.includes("$")) prefix = "$";
    else if (cLower.includes("eur") || cLower.includes("€")) prefix = "€";
    else if (cLower.includes("gbp") || cLower.includes("£")) prefix = "£";
    else if (isIndianCurrency(currency)) prefix = "₹";
  }

  const useIndian = forceIndian !== null ? forceIndian : (isIndianCurrency(currency) || prefix === "₹");
  const sign = num < 0 ? "-" : "";
  const absNum = Math.abs(num);

  if (useIndian) {
    if (absNum >= 1e7) {
      const v = (absNum / 1e7).toFixed(decimals);
      return `${sign}${prefix}${v}Cr`;
    } else if (absNum >= 1e5) {
      const v = (absNum / 1e5).toFixed(decimals);
      return `${sign}${prefix}${v}L`;
    } else if (absNum >= 1e3) {
      const v = (absNum / 1e3).toFixed(decimals);
      return `${sign}${prefix}${v}K`;
    }
  } else {
    if (absNum >= 1e9) {
      const v = (absNum / 1e9).toFixed(decimals);
      return `${sign}${prefix}${v}B`;
    } else if (absNum >= 1e6) {
      const v = (absNum / 1e6).toFixed(decimals);
      return `${sign}${prefix}${v}M`;
    } else if (absNum >= 1e3) {
      const v = (absNum / 1e3).toFixed(decimals);
      return `${sign}${prefix}${v}K`;
    }
  }

  // Regular number under 1,000
  if (Number.isInteger(absNum)) {
    return `${sign}${prefix}${absNum.toLocaleString()}`;
  }
  return `${sign}${prefix}${absNum.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: decimals })}`;
}

export function formatNumber(val, { decimals = 2, compact = false, currency = null } = {}) {
  if (compact) {
    return formatCompactNumber(val, { decimals: 1, currency });
  }
  if (val === null || val === undefined || val === "") return "—";
  const num = Number(val);
  if (isNaN(num)) return String(val);

  const isInt = Number.isInteger(num);
  return num.toLocaleString(undefined, {
    minimumFractionDigits: isInt ? 0 : Math.min(decimals, 2),
    maximumFractionDigits: decimals,
  });
}

export function formatCurrency(val, { currency = "INR", compact = false } = {}) {
  return formatCompactNumber(val, { currency, decimals: 1 });
}

export function formatPercent(val, { decimals = 1, isFraction = false } = {}) {
  if (val === null || val === undefined || val === "") return "—";
  let num = Number(val);
  if (isNaN(num)) return String(val);
  if (isFraction) num *= 100;
  return `${num.toFixed(decimals)}%`;
}

export function truncateLabel(label, maxLen = 24) {
  if (label === null || label === undefined) return "";
  const s = String(label).trim();
  if (s.length > maxLen) {
    return s.slice(0, maxLen - 3).trim() + "...";
  }
  return s;
}

export function formatDate(val, { style = "medium", grain = null } = {}) {
  if (!val) return "—";
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) return String(val);

    if (grain === "year") {
      return d.getFullYear().toString();
    }
    if (grain === "quarter") {
      const q = Math.floor(d.getMonth() / 3) + 1;
      return `Q${q} ${d.getFullYear()}`;
    }
    if (grain === "month") {
      return d.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
    }
    if (grain === "day") {
      return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
    }

    if (style === "short") {
      return d.toLocaleDateString("en-IN", { year: "numeric", month: "2-digit", day: "2-digit" });
    }
    return d.toLocaleDateString("en-IN", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return String(val);
  }
}

export function formatDateTime(val) {
  if (!val) return "—";
  try {
    const d = new Date(val);
    if (isNaN(d.getTime())) return String(val);
    return d.toLocaleString("en-IN", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true,
    });
  } catch {
    return String(val);
  }
}

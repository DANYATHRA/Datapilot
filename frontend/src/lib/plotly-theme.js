/**
 * Central Plotly Enterprise Theme Engine for DataPilot.
 * Strict specifications:
 * - Transparent background
 * - IBM Plex Sans 12px, text #0F1B2D (#F8FAFC dark), secondary #566274 (#94A3B8 dark)
 * - NO title inside figure (card header carries title and subtitle)
 * - Horizontal light gridlines only (#E3E8EE); no vertical gridlines; no zero-line clutter
 * - Axis line only on baseline; automargin: true
 * - Color-blind-safe palette of at most 6 colors (top 5 + "Other" in #94A3B8)
 * - Legend: horizontal, top-left, outside plot area
 * - Hover: dark sleek tooltip with IBM Plex Sans 12px white text
 * - Mode bar: hidden by default, shows only toImage and resetScale2d on hover
 * - Animations off: transition duration 0
 */

// Color-blind safe palette (Wong / Okabe-Ito adapted for high contrast)
export const BRAND_PRIMARY = "#2563EB";
export const OTHER_GREY = "#94A3B8";

export const CATEGORICAL_PALETTE = [
  "#2563EB", // Brand Blue
  "#0D9488", // Teal
  "#D97706", // Amber
  "#7C3AED", // Violet
  "#DC2626", // Red / Coral
  "#0284C7", // Sky Blue
];

// Single-hue sequential for heatmaps
export const SEQUENTIAL_PALETTE = [
  "#eff6ff",
  "#dbeafe",
  "#bfdbfe",
  "#93c5fd",
  "#60a5fa",
  "#3b82f6",
  "#2563eb",
  "#1d4ed8",
];

// Diverging for correlations with neutral midpoint
export const DIVERGING_PALETTE = [
  "#2563eb", // Positive Blue
  "#93c5fd",
  "#f1f5f9", // Neutral midpoint
  "#fdba74",
  "#ea580c", // Negative Orange
];

export function getPlotlyTheme(isDark = false) {
  const textColor = isDark ? "#F8FAFC" : "#0F1B2D";
  const secondaryColor = isDark ? "#94A3B8" : "#566274";
  const gridColor = isDark ? "rgba(255, 255, 255, 0.08)" : "#E3E8EE";
  const baselineColor = isDark ? "#334155" : "#CBD5E1";

  return {
    colorway: CATEGORICAL_PALETTE,
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: {
      family: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
      size: 12,
      color: textColor,
    },
    // NO title inside the figure (card header carries the title and subtitle)
    title: {
      text: "",
    },
    margin: { l: 48, r: 24, t: 16, b: 40, pad: 4 },
    transition: {
      duration: 0, // Animations off
    },
    legend: {
      font: {
        family: "'IBM Plex Sans', sans-serif",
        size: 11,
        color: secondaryColor,
      },
      bgcolor: "rgba(0,0,0,0)",
      orientation: "h",
      x: 0,
      y: 1.14,
      xanchor: "left",
      yanchor: "bottom",
    },
    xaxis: {
      automargin: true,
      showgrid: false, // No vertical gridlines for standard vertical charts
      zeroline: false, // No zero-line clutter
      showline: true, // Axis line only on the baseline
      linecolor: baselineColor,
      linewidth: 1,
      tickfont: {
        size: 11,
        color: secondaryColor,
        family: "'IBM Plex Mono', monospace",
      },
      titlefont: {
        size: 12,
        color: textColor,
        family: "'IBM Plex Sans', sans-serif",
      },
    },
    yaxis: {
      automargin: true,
      showgrid: true, // Horizontal light gridlines only
      gridcolor: gridColor,
      gridwidth: 1,
      zeroline: false, // No zero-line clutter
      showline: false,
      tickfont: {
        size: 11,
        color: secondaryColor,
        family: "'IBM Plex Mono', monospace",
      },
      titlefont: {
        size: 12,
        color: textColor,
        family: "'IBM Plex Sans', sans-serif",
      },
    },
    hoverlabel: {
      bgcolor: "#0F1B2D",
      bordercolor: "#1E293B",
      font: {
        family: "'IBM Plex Sans', -apple-system, BlinkMacSystemFont, sans-serif",
        size: 12,
        color: "#FFFFFF",
      },
    },
  };
}

export const PLOTLY_CONFIG = {
  responsive: true,
  displaylogo: false,
  displayModeBar: "hover", // Mode bar hidden by default; show only on hover
  // Show only Download PNG and Reset zoom; remove all clutter
  modeBarButtons: [["toImage", "resetScale2d"]],
  toImageButtonOptions: {
    format: "png",
    filename: "datapilot_chart",
    height: 600,
    width: 900,
    scale: 2,
  },
};

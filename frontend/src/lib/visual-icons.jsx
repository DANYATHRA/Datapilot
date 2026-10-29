import React from "react";
import {
  BarChart2,
  BarChart3,
  LineChart,
  PieChart,
  ScatterChart,
  Table as TableIcon,
  Gauge,
  Layers,
  Activity,
  GitCommit,
  Hash,
  TrendingUp,
  Percent,
  ListOrdered,
  LayoutGrid,
  Filter,
} from "lucide-react";

export function getVisualTypeIcon(type, className = "w-4 h-4") {
  switch (type) {
    case "kpi_card":
      return <Hash className={className} strokeWidth={1.75} />;
    case "sparkline_kpi":
      return <TrendingUp className={className} strokeWidth={1.75} />;
    case "gauge":
    case "bullet":
      return <Gauge className={className} strokeWidth={1.75} />;
    case "column":
    case "bar":
      return <BarChart2 className={className} strokeWidth={1.75} />;
    case "stacked_column":
    case "stacked_bar":
    case "combo":
      return <BarChart3 className={className} strokeWidth={1.75} />;
    case "line":
    case "area":
      return <LineChart className={className} strokeWidth={1.75} />;
    case "pie":
    case "donut":
      return <PieChart className={className} strokeWidth={1.75} />;
    case "scatter":
    case "bubble":
      return <ScatterChart className={className} strokeWidth={1.75} />;
    case "treemap":
    case "funnel":
      return <Filter className={className} strokeWidth={1.75} />;
    case "heatmap":
    case "pivot":
      return <LayoutGrid className={className} strokeWidth={1.75} />;
    case "histogram":
    case "box":
      return <Activity className={className} strokeWidth={1.75} />;
    case "table":
    case "likert_stack":
    default:
      return <TableIcon className={className} strokeWidth={1.75} />;
  }
}

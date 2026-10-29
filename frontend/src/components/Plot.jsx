import React from "react";
import ChartWrapper from "./ui/chart-wrapper";

export default function PlotView({ data, layout, config, height = 340, className = "" }) {
  return (
    <ChartWrapper
      data={data}
      layout={layout}
      config={config}
      height={height}
      className={className}
    />
  );
}

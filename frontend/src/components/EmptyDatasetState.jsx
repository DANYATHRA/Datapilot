import React from "react";
import { EmptyState } from "./ui/empty-state";
import { Upload } from "lucide-react";

export default function EmptyDatasetState({ onUploadClick, featureName = "analytics" }) {
  return (
    <EmptyState
      title="Upload an Excel file to get started"
      description={`No dataset is currently loaded. Ingest business data in .xlsx, .csv, or .parquet to unlock automated 10-stage cleaning, DuckDB querying, and ${featureName}.`}
      actionLabel="Upload an Excel file"
      onAction={onUploadClick}
      icon={Upload}
    />
  );
}

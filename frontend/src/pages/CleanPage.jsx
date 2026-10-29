import React from "react";
import EditableSpreadsheet from "../components/EditableSpreadsheet";

export default function CleanPage({ ds, onRefresh, onFinishCleaning }) {
  const qualityScore = ds?.quality_score || ds?.quality?.score || 82;

  return (
    <div className="flex flex-col h-full overflow-hidden bg-[#f8fafc]">
      {/* Minimal Header: Title "Clean data", file name, small quality score. No description. */}
      <div className="px-6 py-3.5 border-b border-[#E4E7EC] bg-white flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold text-[#101828]">Clean data</h1>
          <span
            id="clean-page-filename"
            className="text-sm font-medium text-[#475467] bg-[#F2F4F7] px-2.5 py-0.5 rounded-md truncate max-w-xs"
            title={ds?.name || "Dataset"}
          >
            {ds?.name || "Dataset"}
          </span>
        </div>
        <div
          id="clean-page-quality-badge"
          className="text-xs font-semibold text-[#0B7A75] bg-[#0B7A75]/10 px-2.5 py-1 rounded-md tabular-nums"
        >
          Quality: {qualityScore}%
        </div>
      </div>

      {/* The editable grid is the entire page */}
      <div className="flex-1 overflow-auto p-4">
        <EditableSpreadsheet
          ds={ds}
          onRefresh={onRefresh}
          onFinishCleaning={onFinishCleaning}
        />
      </div>
    </div>
  );
}


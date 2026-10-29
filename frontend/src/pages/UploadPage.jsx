import React, { useState } from "react";
import { UploadCloud, Loader2 } from "lucide-react";
import { upload, loadSample } from "../api";
import { toast } from "sonner";

export default function UploadPage({ onDatasetUploaded }) {
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  const handleFileUpload = async (file) => {
    console.log("inside handleFileUpload:", file?.name);
    if (!file) return;
    const name = file.name.toLowerCase();
    const isSupported = name.endsWith(".xlsx") || name.endsWith(".xls") || name.endsWith(".csv");
    if (!isSupported) {
      toast.error("Please upload an Excel (.xlsx, .xls) or CSV file");
      return;
    }

    try {
      setLoading(true);
      console.log("calling upload(file)...");
      const res = await upload(file);
      console.log("upload result:", res);
      const newId = res?.dataset_id || res?.id;
      if (newId) {
        toast.success("File uploaded successfully");
        onDatasetUploaded(newId);
      } else {
        toast.error("Failed to parse uploaded file");
      }
    } catch (err) {
      console.error("upload error:", err);
      toast.error(err.message || "Failed to upload file");
    } finally {
      setLoading(false);
    }
  };

  const handleLoadSample = async (sampleName) => {
    try {
      setLoading(true);
      const res = await loadSample(sampleName);
      const newId = res?.dataset_id || res?.id;
      if (newId) {
        toast.success(`Loaded ${sampleName}`);
        onDatasetUploaded(newId);
      }
    } catch (err) {
      toast.error(err.message || "Failed to load sample dataset");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-6 py-10">
      {/* Minimal Header (1-3 words) */}
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-[#101828]">Upload data</h1>
      </div>

      {/* Plain Dropzone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (e.dataTransfer.files?.[0]) {
            handleFileUpload(e.dataTransfer.files[0]);
          }
        }}
        className={`border-2 border-dashed rounded-2xl p-12 text-center transition-all bg-white ${
          dragOver ? "border-[#0B7A75] bg-[#0B7A75]/5" : "border-[#E4E7EC] hover:border-[#CBD5E1]"
        }`}
      >
        <div className="w-12 h-12 rounded-full bg-[#0B7A75]/10 text-[#0B7A75] flex items-center justify-center mx-auto mb-4">
          <UploadCloud className="w-6 h-6" />
        </div>

        <h2 className="text-base font-semibold text-[#101828] mb-1">
          Choose a file or drag it here
        </h2>
        <p className="text-xs text-[#475467] mb-6">
          Supports Excel (.xlsx, .xls) and CSV files
        </p>

        <label className="inline-flex">
          <input
            id="file-upload-input"
            type="file"
            accept=".xlsx,.xls,.csv"
            className="sr-only"
            disabled={loading}
            onChange={(e) => {
              console.log("File input changed:", e.target.files?.[0]?.name);
              if (e.target.files?.[0]) {
                handleFileUpload(e.target.files[0]);
              }
            }}
          />
          <span
            id="btn-choose-file"
            className="cursor-pointer px-4 py-2 rounded-lg text-sm font-semibold bg-[#0B7A75] text-white hover:bg-[#085854] transition-colors inline-flex items-center gap-2 shadow-xs"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Loading...</span>
              </>
            ) : (
              <span>Select file</span>
            )}
          </span>
        </label>
      </div>

      {/* Sample datasets */}
      <div className="mt-8 pt-6 border-t border-[#E4E7EC] flex items-center justify-between">
        <span className="text-xs font-medium text-[#475467]">Or try sample data:</span>
        <div className="flex items-center gap-3">
          <button
            type="button"
            id="btn-sample-sales"
            disabled={loading}
            onClick={() => handleLoadSample("datapilot_test_sales.xlsx")}
            className="text-xs font-medium text-[#0B7A75] hover:underline"
          >
            Sales dataset (.xlsx)
          </button>
          <span className="text-[#CBD5E1]">·</span>
          <button
            type="button"
            id="btn-sample-students"
            disabled={loading}
            onClick={() => handleLoadSample("students.xlsx")}
            className="text-xs font-medium text-[#0B7A75] hover:underline"
          >
            Student records (.xlsx)
          </button>
        </div>
      </div>
    </div>
  );
}

import { UploadCloud, Table, LayoutDashboard } from "lucide-react";

/**
 * Three-Step Focused Navigation for DataPilot:
 * 1. Upload (/upload)
 * 2. Clean (/clean)
 * 3. Dashboard (/dashboard)
 */
export const STEPS = [
  {
    stepNumber: 1,
    id: "upload",
    path: "/upload",
    label: "Upload",
    desc: "Upload Excel or CSV file",
    icon: UploadCloud,
  },
  {
    stepNumber: 2,
    id: "clean",
    path: "/clean",
    label: "Clean",
    desc: "Review and fix data issues",
    icon: Table,
  },
  {
    stepNumber: 3,
    id: "dashboard",
    path: "/dashboard",
    label: "Dashboard",
    desc: "Interactive charts and key insights",
    icon: LayoutDashboard,
  },
];

export function getStepByPath(pathname) {
  const cleanPath = (pathname || "").toLowerCase().split("?")[0];
  if (cleanPath.startsWith("/clean")) return STEPS[1];
  if (cleanPath.startsWith("/dashboard")) return STEPS[2];
  return STEPS[0];
}

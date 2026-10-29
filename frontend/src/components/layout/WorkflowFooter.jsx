import React from "react";
import { ArrowRight } from "lucide-react";
import { Button } from "../ui/button";
import { getStepByPath } from "../../navConfig";

/**
 * Standardized WorkflowFooter driven directly from navConfig.
 * Ensures the "Next" button always displays the correct next step label
 * and routes to the exact next step without hardcoded mismatches.
 */
export function WorkflowFooter({
  currentPath,
  hasRatingScale = false,
  onNavigate,
  extraActions,
  className = "",
}) {
  const { nextStep } = getStepByPath(currentPath, hasRatingScale);

  if (!nextStep) return null;

  return (
    <div className={`flex items-center justify-end gap-3 pt-6 mt-6 border-t border-border/60 ${className}`}>
      {extraActions}

      <Button
        id={`btn-next-${nextStep.id}`}
        onClick={() => onNavigate && onNavigate(nextStep.path)}
        className="gap-2 h-10 px-6 font-medium text-sm"
      >
        <span>Next: {nextStep.label}</span>
        <ArrowRight className="w-4 h-4" strokeWidth={1.75} />
      </Button>
    </div>
  );
}

export default WorkflowFooter;

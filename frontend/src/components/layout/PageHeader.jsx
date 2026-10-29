import React from "react";
import { useLocation } from "react-router-dom";
import { cn } from "../../lib/utils";
import { getStepByPath } from "../../navConfig";

/**
 * Standardized PageHeader component matching DataPilot design guidelines:
 * - Eyebrow: text-xs (12px) font-medium (500) text-muted-foreground (no all-caps tracking, no mono)
 * - Page title: text-[28px] font-semibold (600) leading-tight text-foreground (not larger)
 * - Description: text-sm (14px) font-normal (400) text-muted-foreground leading-normal max-w-3xl
 * - Auto-resolves stepNumber and stepTotal from current route via navConfig
 * - Aligns icon tile, title, description, and actions to the exact same left edge
 */
export function PageHeader({
  icon: Icon,
  stepNumber,
  stepTotal,
  eyebrow,
  group,
  title,
  description,
  actions,
  className = "",
  hasRatingScale = false,
}) {
  const location = useLocation();
  const navInfo = getStepByPath(location.pathname, hasRatingScale);

  const resolvedStepNumber = stepNumber !== undefined ? stepNumber : navInfo.stepNumber;
  const resolvedStepTotal = stepTotal !== undefined ? stepTotal : navInfo.totalSteps;
  const resolvedGroup = group !== undefined ? group : navInfo.item?.group;

  let computedEyebrow = eyebrow;
  if (!computedEyebrow) {
    if (resolvedStepNumber != null) {
      computedEyebrow = `Step ${resolvedStepNumber} of ${resolvedStepTotal}`;
      if (resolvedGroup) {
        const groupLabel = resolvedGroup.charAt(0) + resolvedGroup.slice(1).toLowerCase();
        computedEyebrow += ` · ${groupLabel}`;
      }
    } else {
      computedEyebrow = navInfo.eyebrow || "Workspace";
    }
  }

  return (
    <div
      className={cn(
        "flex flex-col md:flex-row md:items-start justify-between gap-4 pb-6 mb-6 border-b border-border/70",
        className
      )}
    >
      <div className="flex items-start gap-4">
        {Icon && (
          <div className="w-10 h-10 rounded-lg bg-primary/10 text-primary flex items-center justify-center shrink-0 mt-0.5">
            <Icon className="w-5 h-5" strokeWidth={1.75} aria-hidden="true" />
          </div>
        )}
        <div className="space-y-1">
          {computedEyebrow && (
            <div className="text-xs font-medium text-muted-foreground">
              {computedEyebrow}
            </div>
          )}
          <h1 className="text-[28px] font-semibold tracking-tight text-foreground leading-tight">
            {title}
          </h1>
          {description && (
            <p className="text-sm font-normal text-muted-foreground leading-normal max-w-3xl pt-0.5">
              {description}
            </p>
          )}
        </div>
      </div>

      {actions && (
        <div className="flex items-center gap-2.5 shrink-0 self-start md:self-start pt-1">
          {actions}
        </div>
      )}
    </div>
  );
}

export default PageHeader;

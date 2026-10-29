import React from "react";

export function LogoMark({ className = "w-7 h-7", size = 28 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="dp-mark-grad" x1="4" y1="4" x2="44" y2="44" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0B7A75" />
          <stop offset="100%" stopColor="#085854" />
        </linearGradient>
        <linearGradient id="dp-needle-grad" x1="16" y1="32" x2="32" y2="16" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.95" />
          <stop offset="100%" stopColor="#e2f4f3" />
        </linearGradient>
      </defs>
      {/* Geometric Hexagonal Shield with Rounded Vertices */}
      <rect x="4" y="4" width="40" height="40" rx="10" fill="url(#dp-mark-grad)" />
      {/* Precision Compass Needle Outline */}
      <path
        d="M24 10L35 21L24 38L13 21L24 10Z"
        stroke="#ffffff"
        strokeWidth="2"
        strokeLinejoin="round"
        fill="none"
        opacity="0.4"
      />
      {/* North-East Precision Navigator Needle */}
      <path d="M24 13L33 22L24 25L21 24L24 13Z" fill="url(#dp-needle-grad)" />
      <path d="M24 35L15 26L24 23L27 24L24 35Z" fill="#24b8b1" opacity="0.75" />
      {/* Center Analytical Axis Nodes */}
      <circle cx="24" cy="24" r="3.5" fill="#ffffff" />
      <circle cx="24" cy="24" r="1.5" fill="#0B7A75" />
    </svg>
  );
}

export function Logo({
  showBadge = true,
  badgeText = "ENTERPRISE",
  className = "",
  size = "default",
  iconOnly = false,
}) {
  const isSmall = size === "sm";
  const isLarge = size === "lg";

  const markSize = isSmall ? 22 : isLarge ? 36 : 28;
  const markClass = isSmall ? "w-5.5 h-5.5" : isLarge ? "w-9 h-9" : "w-7 h-7";

  if (iconOnly) {
    return (
      <div className={`flex items-center justify-center select-none ${className}`} title="DataPilot">
        <LogoMark size={markSize} className={markClass} />
      </div>
    );
  }

  return (
    <div className={`flex items-center gap-2.5 select-none ${className}`}>
      <LogoMark size={markSize} className={markClass} />
      <div className="flex flex-col leading-none">
        <div className="flex items-center gap-1.5">
          <span
            className={`font-bold tracking-tight text-foreground ${
              isSmall ? "text-sm" : isLarge ? "text-xl" : "text-base"
            }`}
          >
            Data<span className="text-primary">Pilot</span>
          </span>
          {showBadge && !isSmall && (
            <span className="text-[10px] font-semibold tracking-wider px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
              {badgeText}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default Logo;

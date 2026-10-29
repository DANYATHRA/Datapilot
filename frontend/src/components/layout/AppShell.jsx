import React, { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  UploadCloud,
  Table,
  LayoutDashboard,
  Lock,
  LogOut,
  Menu,
  X,
} from "lucide-react";
import { Logo } from "../brand/Logo";
import { cn } from "../../lib/utils";
import { STEPS } from "../../navConfig";

export function AppShell({
  user,
  onSignOut,
  dataset,
  isCleanFinished = false,
  children,
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const hasDataset = Boolean(dataset);
  const currentPath = location.pathname;

  // Step access rules:
  // Step 1 (Upload): Always unlocked
  // Step 2 (Clean): Unlocked after dataset uploaded
  // Step 3 (Dashboard): Unlocked after dataset uploaded & finish cleaning (or dataset is cleaned)
  const isStepUnlocked = (stepNumber) => {
    if (stepNumber === 1) return true;
    if (stepNumber === 2) return hasDataset;
    if (stepNumber === 3) return hasDataset && (isCleanFinished || dataset?.current_version > 1 || dataset?.is_cleaned);
    return false;
  };

  return (
    <div className="flex h-screen w-full bg-[#f8fafc] text-[#101828] overflow-hidden antialiased font-sans">
      {/* ── DESKTOP SIDEBAR (Three Steps Only) ────────────────────────── */}
      <aside className="hidden md:flex flex-col w-60 shrink-0 border-r border-[#E4E7EC] bg-white z-20">
        {/* Top Logo */}
        <div className="h-16 px-5 border-b border-[#E4E7EC] flex items-center justify-between">
          <Link to="/upload" className="flex items-center gap-2.5 focus:outline-hidden">
            <Logo showBadge={false} size="sm" />
          </Link>
        </div>

        {/* 3 Steps Navigation */}
        <nav className="flex-1 px-3 py-5 space-y-1.5 overflow-y-auto">
          {STEPS.map((step) => {
            const unlocked = isStepUnlocked(step.stepNumber);
            const isActive = currentPath.startsWith(step.path);
            const Icon = step.icon;

            return (
              <button
                key={step.id}
                type="button"
                id={`nav-step-${step.id}`}
                disabled={!unlocked}
                onClick={() => {
                  if (unlocked) {
                    navigate(step.path);
                  }
                }}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-left font-medium",
                  isActive
                    ? "bg-[#0B7A75]/10 text-[#0B7A75] font-semibold"
                    : unlocked
                    ? "text-[#475467] hover:bg-[#F2F4F7] hover:text-[#101828]"
                    : "text-[#98A2B3] cursor-not-allowed opacity-60"
                )}
              >
                <div
                  className={cn(
                    "w-6 h-6 rounded-full flex items-center justify-center text-xs shrink-0 font-semibold",
                    isActive
                      ? "bg-[#0B7A75] text-white"
                      : unlocked
                      ? "bg-[#F2F4F7] text-[#475467]"
                      : "bg-[#F2F4F7] text-[#98A2B3]"
                  )}
                >
                  {step.stepNumber}
                </div>
                <div className="flex-1 truncate">
                  <span>{step.label}</span>
                </div>
                {!unlocked && <Lock className="w-3.5 h-3.5 text-[#98A2B3] shrink-0" />}
              </button>
            );
          })}
        </nav>

        {/* User Account / Sign Out at Bottom */}
        <div className="p-3 border-t border-[#E4E7EC]">
          <div className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-[#F8FAFC]">
            <div className="truncate text-xs font-medium text-[#475467]" title={user}>
              {user || "user@datapilot.app"}
            </div>
            <button
              type="button"
              id="btn-nav-signout"
              onClick={onSignOut}
              className="p-1 rounded text-[#475467] hover:text-[#DC2626] transition-colors"
              title="Sign out"
              aria-label="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* ── MOBILE HEADER & MENU ────────────────────────────────────── */}
      <div className="flex-1 flex flex-col h-full min-w-0 overflow-hidden">
        <header className="md:hidden h-14 px-4 bg-white border-b border-[#E4E7EC] flex items-center justify-between shrink-0 z-30">
          <Link to="/upload" className="flex items-center gap-2">
            <Logo showBadge={false} size="sm" />
          </Link>
          <button
            type="button"
            id="btn-mobile-nav-toggle"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 rounded text-[#475467] hover:bg-[#F2F4F7]"
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </header>

        {mobileMenuOpen && (
          <div className="md:hidden bg-white border-b border-[#E4E7EC] px-4 py-3 space-y-2 z-30">
            {STEPS.map((step) => {
              const unlocked = isStepUnlocked(step.stepNumber);
              const isActive = currentPath.startsWith(step.path);

              return (
                <button
                  key={step.id}
                  disabled={!unlocked}
                  onClick={() => {
                    if (unlocked) {
                      navigate(step.path);
                      setMobileMenuOpen(false);
                    }
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-left font-medium",
                    isActive
                      ? "bg-[#0B7A75]/10 text-[#0B7A75] font-semibold"
                      : unlocked
                      ? "text-[#475467] hover:bg-[#F2F4F7]"
                      : "text-[#98A2B3] opacity-60"
                  )}
                >
                  <span className="w-5 h-5 rounded-full bg-[#F2F4F7] text-xs flex items-center justify-center">
                    {step.stepNumber}
                  </span>
                  <span>{step.label}</span>
                  {!unlocked && <Lock className="w-3.5 h-3.5 ml-auto text-[#98A2B3]" />}
                </button>
              );
            })}
            <div className="pt-2 border-t border-[#E4E7EC] flex items-center justify-between">
              <span className="text-xs text-[#475467] truncate">{user}</span>
              <button
                type="button"
                onClick={onSignOut}
                className="text-xs font-medium text-[#DC2626]"
              >
                Sign out
              </button>
            </div>
          </div>
        )}

        {/* ── MAIN CONTENT AREA ─────────────────────────────────────── */}
        <main className="flex-1 overflow-auto bg-[#f8fafc]">
          {children}
        </main>
      </div>
    </div>
  );
}

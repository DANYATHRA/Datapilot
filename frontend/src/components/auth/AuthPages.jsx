import React, { useState, useEffect } from "react";
import {
  Eye,
  EyeOff,
  Mail,
  Lock,
  User,
  ShieldCheck,
  CircleCheck,
  TriangleAlert,
  ArrowRight,
  Database,
  ChartColumn,
  MessageSquareText,
} from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Checkbox } from "../ui/checkbox";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "../ui/dialog";
import { LogoMark } from "../brand/Logo";
import { api, setToken } from "../../api";

export function AuthPage({ onDone, onAuthSuccess, initialError = "" }) {
  const [mode, setMode] = useState("login"); // "login" | "register" | "forgot" | "reset"
  const [ssoProvider, setSsoProvider] = useState(null);
  const [email, setEmail] = useState(() => localStorage.getItem("dp_saved_email") || "");
  const [password, setPassword] = useState(() => localStorage.getItem("dp_saved_pw") || "");
  const [name, setName] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [resetCode, setResetCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmNewPw, setConfirmNewPw] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [showCPw, setShowCPw] = useState(false);
  const [rememberMe, setRememberMe] = useState(!!localStorage.getItem("dp_saved_email"));
  const [err, setErr] = useState(initialError);
  const [info, setInfo] = useState("");
  const [loading, setLoading] = useState(false);

  const notifySuccess = (token, userEmail) => {
    if (onAuthSuccess) {
      onAuthSuccess(token, userEmail);
    } else if (onDone) {
      onDone(userEmail);
    }
  };

  useEffect(() => {
    if (initialError) setErr(initialError);
  }, [initialError]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErr("");
    setInfo("");
    setLoading(true);

    try {
      if (mode === "login") {
        const res = await api("/auth/login", {
          method: "POST",
          body: { email: email.trim(), password },
        });
        if (rememberMe) {
          localStorage.setItem("dp_saved_email", email.trim());
          localStorage.setItem("dp_saved_pw", password);
        } else {
          localStorage.removeItem("dp_saved_email");
          localStorage.removeItem("dp_saved_pw");
        }
        setToken(res.token);
        notifySuccess(res.token, res.email);
      } else if (mode === "register") {
        if (password.length < 8) {
          setErr("Password must be at least 8 characters long.");
          setLoading(false);
          return;
        }
        if (password !== confirmPw) {
          setErr("Passwords do not match.");
          setLoading(false);
          return;
        }
        const res = await api("/auth/register", {
          method: "POST",
          body: { email: email.trim(), password, name: name.trim() || undefined },
        });
        setToken(res.token);
        notifySuccess(res.token, res.email);
      } else if (mode === "forgot") {
        await api("/auth/forgot-password", {
          method: "POST",
          body: { email: email.trim() },
        });
        setInfo("If an account exists, a reset code was generated.");
        setMode("reset");
      } else if (mode === "reset") {
        if (newPassword.length < 8) {
          setErr("New password must be at least 8 characters long.");
          setLoading(false);
          return;
        }
        if (newPassword !== confirmNewPw) {
          setErr("Passwords do not match.");
          setLoading(false);
          return;
        }
        await api("/auth/reset-password", {
          method: "POST",
          body: { email: email.trim(), code: resetCode.trim(), new_password: newPassword },
        });
        setInfo("Password reset successful. Sign in with your new credentials.");
        setMode("login");
      }
    } catch (ex) {
      setErr(ex.message || "Action failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full flex bg-background text-foreground">
      {/* Left Column: Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md space-y-6">
          {/* Logo & Headline */}
          <div className="space-y-2">
            <div className="flex items-center gap-2.5 mb-6">
              <LogoMark size={32} className="w-8 h-8" />
              <span className="text-xl font-bold tracking-tight text-foreground">
                Data<span className="text-primary">Pilot</span>
              </span>
              <span className="text-[10px] font-semibold tracking-wider px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20">
                ENTERPRISE
              </span>
            </div>

            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {mode === "login" && "Sign in"}
              {mode === "register" && "Create account"}
              {mode === "forgot" && "Reset password"}
              {mode === "reset" && "Enter new password"}
            </h1>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {mode === "login" && "Enter your email and password to access your data workspace."}
              {mode === "register" && "Set up an analyst account to clean, explore, and report on enterprise data."}
              {mode === "forgot" && "We will verify your account and provide a reset code."}
              {mode === "reset" && "Enter your verification code and choose a new password."}
            </p>
          </div>

          {/* Error & Info Alerts */}
          {err && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-destructive text-xs">
              <TriangleAlert className="w-4 h-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
              <span>{err}</span>
            </div>
          )}
          {info && (
            <div className="flex items-center gap-2 p-3 rounded-lg bg-info/10 border border-info/20 text-info text-xs">
              <CircleCheck className="w-4 h-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
              <span>{info}</span>
            </div>
          )}

          {/* Main Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="auth-name">Full name</Label>
                <div className="relative">
                  <User className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                  <Input
                    id="auth-name"
                    type="text"
                    placeholder="Alex Morgan"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="pl-9 h-10 text-xs"
                  />
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="auth-email">Work email</Label>
              <div className="relative">
                <Mail className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                <Input
                  id="auth-email"
                  type="email"
                  placeholder="analyst@enterprise.com"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="pl-9 h-10 text-xs"
                />
              </div>
            </div>

            {(mode === "login" || mode === "register") && (
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <Label htmlFor="auth-pw">Password</Label>
                  {mode === "login" && (
                    <button
                      type="button"
                      onClick={() => { setErr(""); setInfo(""); setMode("forgot"); }}
                      className="text-xs text-primary hover:underline font-medium"
                    >
                      Forgot password?
                    </button>
                  )}
                </div>
                <div className="relative">
                  <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                  <Input
                    id="auth-pw"
                    type={showPw ? "text" : "password"}
                    placeholder="Enter password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="pl-9 pr-9 h-10 text-xs font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPw((v) => !v)}
                    className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"
                    aria-label={showPw ? "Hide password" : "Show password"}
                  >
                    {showPw ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
                  </button>
                </div>
                {mode === "register" && (
                  <p className="text-[11px] text-muted-foreground">
                    Must be at least 8 characters long.
                  </p>
                )}
              </div>
            )}

            {mode === "register" && (
              <div className="space-y-1.5">
                <Label htmlFor="auth-confirm-pw">Confirm password</Label>
                <div className="relative">
                  <Lock className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" strokeWidth={1.75} />
                  <Input
                    id="auth-confirm-pw"
                    type={showCPw ? "text" : "password"}
                    placeholder="Repeat password"
                    required
                    value={confirmPw}
                    onChange={(e) => setConfirmPw(e.target.value)}
                    className="pl-9 pr-9 h-10 text-xs font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowCPw((v) => !v)}
                    className="absolute right-3 top-3 text-muted-foreground hover:text-foreground"
                    aria-label={showCPw ? "Hide password" : "Show password"}
                  >
                    {showCPw ? <EyeOff className="h-4 w-4" strokeWidth={1.75} /> : <Eye className="h-4 w-4" strokeWidth={1.75} />}
                  </button>
                </div>
              </div>
            )}

            {mode === "reset" && (
              <>
                <div className="space-y-1.5">
                  <Label htmlFor="reset-code">Verification code</Label>
                  <Input
                    id="reset-code"
                    type="text"
                    placeholder="Enter 6-digit code"
                    required
                    value={resetCode}
                    onChange={(e) => setResetCode(e.target.value)}
                    className="h-10 text-xs font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="new-pw">New password</Label>
                  <Input
                    id="new-pw"
                    type="password"
                    placeholder="Enter new password"
                    required
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="h-10 text-xs font-mono"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="confirm-new-pw">Confirm new password</Label>
                  <Input
                    id="confirm-new-pw"
                    type="password"
                    placeholder="Repeat new password"
                    required
                    value={confirmNewPw}
                    onChange={(e) => setConfirmNewPw(e.target.value)}
                    className="h-10 text-xs font-mono"
                  />
                </div>
              </>
            )}

            {mode === "login" && (
              <div className="flex items-center space-x-2 pt-1">
                <Checkbox
                  id="remember-me"
                  checked={rememberMe}
                  onCheckedChange={setRememberMe}
                />
                <label
                  htmlFor="remember-me"
                  className="text-xs text-muted-foreground select-none cursor-pointer"
                >
                  Remember this device for 30 days
                </label>
              </div>
            )}

            <Button
              id="auth-submit"
              type="submit"
              loading={loading}
              className="w-full h-10 font-semibold gap-2 mt-2"
            >
              <span>
                {mode === "login" && "Sign in"}
                {mode === "register" && "Create account"}
                {mode === "forgot" && "Send reset code"}
                {mode === "reset" && "Update password"}
              </span>
              <ArrowRight className="w-4 h-4" strokeWidth={1.75} />
            </Button>
          </form>

          {/* SSO and Social Login */}
          {mode === "login" && (
            <div className="pt-3 border-t border-border/80 space-y-2">
              <div className="text-[11px] text-center text-muted-foreground font-medium">Or continue with</div>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  id="btn-sso-google"
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full text-xs h-9 font-normal"
                  onClick={() => setSsoProvider("google")}
                >
                  Google
                </Button>
                <Button
                  id="btn-sso-github"
                  type="button"
                  variant="outline"
                  size="sm"
                  className="w-full text-xs h-9 font-normal"
                  onClick={() => setSsoProvider("github")}
                >
                  GitHub
                </Button>
              </div>
            </div>
          )}

          {/* Switch link */}
          <div className="text-center text-xs text-muted-foreground pt-3 border-t border-border/80">
            {mode === "login" ? (
              <p>
                Do not have an account?{" "}
                <button
                  type="button"
                  id="btn-switch-register"
                  onClick={() => { setErr(""); setInfo(""); setMode("register"); }}
                  className="text-primary font-semibold hover:underline"
                >
                  Create account
                </button>
              </p>
            ) : (
              <p>
                Already have an account?{" "}
                <button
                  type="button"
                  id="btn-switch-login"
                  onClick={() => { setErr(""); setInfo(""); setMode("login"); }}
                  className="text-primary font-semibold hover:underline"
                >
                  Sign in
                </button>
              </p>
            )}
          </div>
        </div>

        {/* SSO Mock Authentication Modal for Developer / Testing */}
        <Dialog open={!!ssoProvider} onOpenChange={(open) => !open && setSsoProvider(null)}>
          <DialogContent className="max-w-md p-6">
            <DialogHeader>
              <DialogTitle className="text-base font-semibold">
                Instant SSO Authentication
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                Authenticate with {ssoProvider === "google" ? "Google Workspace" : "GitHub Enterprise"} identity provider.
              </DialogDescription>
            </DialogHeader>
            <div className="py-4 space-y-3">
              <div className="p-3 rounded-lg bg-muted text-xs font-mono text-muted-foreground">
                Account: {ssoProvider === "google" ? "google_tester@datapilot.io" : "github_tester@datapilot.io"}
              </div>
              <Button
                id="btn-sso-confirm"
                className="w-full h-10 font-semibold"
                loading={loading}
                onClick={async () => {
                  setLoading(true);
                  try {
                    const provider = ssoProvider || "google";
                    const res = await api("/auth/oauth/mock-login", {
                      method: "POST",
                      body: {
                        provider,
                        email: `${provider}_tester@datapilot.io`,
                        name: `${provider.charAt(0).toUpperCase() + provider.slice(1)} Tester`,
                      },
                    });
                    if (res?.token) {
                      setToken(res.token);
                      localStorage.setItem("dp_email", res.user?.email || `${provider}_tester@datapilot.io`);
                      setSsoProvider(null);
                      notifySuccess(res.token, res.user?.email || `${provider}_tester@datapilot.io`);
                    } else {
                      setErr("SSO verification returned no token");
                    }
                  } catch (e) {
                    setErr(e.message || "SSO error");
                  } finally {
                    setLoading(false);
                  }
                }}
              >
                Sign In as {ssoProvider === "google" ? "Google User" : "GitHub User"}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {/* Right Column: Enterprise Brand Panel */}
      <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-slate-900 via-slate-950 to-primary/40 p-12 flex-col justify-between text-white relative overflow-hidden border-l border-border/20">
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#1e293b15_1px,transparent_1px),linear-gradient(to_bottom,#1e293b15_1px,transparent_1px)] bg-[size:32px_32px]" />

        <div className="relative z-10 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-400" strokeWidth={1.75} />
            <span className="text-xs font-semibold tracking-wider uppercase text-slate-300">
              Enterprise Grade Security
            </span>
          </div>
          <span className="text-xs text-slate-400 font-mono">SOC2 Type II Compliant</span>
        </div>

        <div className="relative z-10 space-y-6 max-w-lg my-auto">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/20 border border-primary/40 text-sky-300 text-xs font-medium">
            <MessageSquareText className="w-3.5 h-3.5" strokeWidth={1.75} />
            <span>Autonomous Data Governance</span>
          </div>

          <h2 className="text-3xl font-bold tracking-tight text-white leading-tight">
            Clean raw data. Query with DuckDB. Deliver verifiable insights.
          </h2>

          <p className="text-slate-300 text-xs leading-relaxed">
            DataPilot provides 10-stage automated semantic data cleaning, immutable Parquet versioning,
            read-only sandboxed SQL execution, and 23 native chart visualizations in a unified platform.
          </p>

          <div className="grid grid-cols-2 gap-4 pt-4 border-t border-slate-800">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-sky-400 text-xs font-semibold">
                <Database className="w-4 h-4" strokeWidth={1.75} />
                <span>In-Process DuckDB</span>
              </div>
              <p className="text-[11px] text-slate-400 leading-normal">
                Sub-second analytical queries on datasets up to millions of records.
              </p>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-emerald-400 text-xs font-semibold">
                <ChartColumn className="w-4 h-4" strokeWidth={1.75} />
                <span>23 Visual Types</span>
              </div>
              <p className="text-[11px] text-slate-400 leading-normal">
                KPIs, distributions, correlations, and survey batteries with formula reconciliation.
              </p>
            </div>
          </div>
        </div>

        <div className="relative z-10 flex items-center justify-between text-xs text-slate-400 pt-6 border-t border-slate-800/80">
          <span>&copy; {new Date().getFullYear()} DataPilot Intelligence Inc.</span>
          <span>Privacy &middot; Terms &middot; Compliance</span>
        </div>
      </div>
    </div>
  );
}

export default AuthPage;

import React from "react";
import { AlertTriangle, RotateCcw, Home } from "lucide-react";
import { Button } from "./ui/button";

export class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("DataPilot caught UI error:", error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  handleHome = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/";
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen bg-background flex items-center justify-center p-6 text-foreground">
          <div className="max-w-md w-full rounded-xl border border-border bg-card p-8 text-center shadow-lg">
            <div className="w-12 h-12 rounded-full bg-destructive/10 text-destructive flex items-center justify-center mx-auto mb-4">
              <AlertTriangle className="w-6 h-6" strokeWidth={1.75} aria-hidden="true" />
            </div>
            <h2 className="text-lg font-semibold text-foreground mb-2">Something went wrong</h2>
            <p className="text-sm text-muted-foreground mb-6 leading-relaxed">
              An unexpected interface error occurred. Your datasets and cleaning versions remain safely preserved in the database.
            </p>
            {this.state.error && (
              <div className="p-3 rounded-md bg-secondary/80 border border-border text-left mb-6 overflow-x-auto">
                <code className="text-xs font-mono text-destructive">
                  {this.state.error.message || String(this.state.error)}
                </code>
              </div>
            )}
            <div className="flex items-center justify-center gap-3">
              <Button variant="outline" onClick={this.handleReset} className="gap-2">
                <RotateCcw className="w-4 h-4" strokeWidth={1.75} />
                <span>Reload Page</span>
              </Button>
              <Button onClick={this.handleHome} className="gap-2">
                <Home className="w-4 h-4" strokeWidth={1.75} />
                <span>Return to Home</span>
              </Button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}

export function NotFoundPage({ onNavigateHome }) {
  return (
    <div className="min-h-[60vh] flex items-center justify-center p-6 text-foreground">
      <div className="max-w-md w-full rounded-xl border border-dashed border-border bg-card p-10 text-center shadow-xs">
        <div className="text-5xl font-bold font-mono text-primary mb-3">404</div>
        <h2 className="text-lg font-semibold text-foreground mb-2">Page Not Found</h2>
        <p className="text-sm text-muted-foreground mb-6">
          The requested analytical workflow step or route does not exist.
        </p>
        <Button onClick={onNavigateHome} className="gap-2">
          <Home className="w-4 h-4" strokeWidth={1.75} />
          <span>Back to Upload</span>
        </Button>
      </div>
    </div>
  );
}

export default ErrorBoundary;

import React, { useCallback, useEffect, useState } from "react";
import { Routes, Route, Navigate, useNavigate, useLocation } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import { AppShell } from "./components/layout/AppShell.jsx";
import { AuthPage } from "./components/auth/AuthPages.jsx";

// Three Focused Pages Only
import UploadPage from "./pages/UploadPage.jsx";
import CleanPage from "./pages/CleanPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();

  // Authentication
  const [token, setAuthToken] = useState(() => getToken());
  const [user, setUser] = useState(() => localStorage.getItem("dp_email") || "");

  // Dataset State
  const [dsId, setDsId] = useState(() => {
    const storedUser = localStorage.getItem("dp_email");
    return storedUser ? localStorage.getItem(`dp_active_ds_${storedUser}`) || "" : "";
  });
  const [ds, setDs] = useState(null);
  const [isCleanFinished, setIsCleanFinished] = useState(() => {
    const storedUser = localStorage.getItem("dp_email");
    const storedDsId = storedUser ? localStorage.getItem(`dp_active_ds_${storedUser}`) || "" : "";
    return storedDsId ? localStorage.getItem(`dp_clean_done_${storedDsId}`) === "true" : false;
  });

  // Sync token to API client
  useEffect(() => {
    if (token) {
      setToken(token);
    }
  }, [token]);

  // Load Active Dataset Details
  const loadActiveDataset = useCallback(
    async (targetId) => {
      const activeId = targetId || dsId;
      if (!activeId) {
        setDs(null);
        return;
      }
      try {
        const data = await api.getDataset(activeId);
        setDs(data);
      } catch {
        setDs(null);
        setDsId("");
        if (user) localStorage.removeItem(`dp_active_ds_${user}`);
      }
    },
    [dsId, user]
  );

  // Refresh dataset details
  const refresh = useCallback(
    async (preferredId) => {
      const target = preferredId || dsId;
      if (target) {
        setDsId(target);
        if (user) localStorage.setItem(`dp_active_ds_${user}`, target);
        await loadActiveDataset(target);
      } else {
        setDs(null);
      }
    },
    [dsId, loadActiveDataset, user]
  );

  // Initial load
  useEffect(() => {
    if (token && dsId) {
      loadActiveDataset(dsId);
    }
  }, [token, dsId, loadActiveDataset]);

  // Auth Handlers
  const handleAuthSuccess = (newToken, email) => {
    setToken(newToken);
    setAuthToken(newToken);
    setUser(email);
    localStorage.setItem("dp_email", email);
  };

  const handleSignOut = () => {
    setToken(null);
    setAuthToken(null);
    setUser("");
    setDsId("");
    setDs(null);
    setIsCleanFinished(false);
    localStorage.removeItem("dp_email");
    if (user) localStorage.removeItem(`dp_active_ds_${user}`);
    navigate("/upload");
  };

  // When a dataset is uploaded
  const handleDatasetUploaded = async (newId) => {
    console.log("inside handleDatasetUploaded, newId:", newId);
    setDsId(newId);
    if (user) localStorage.setItem(`dp_active_ds_${user}`, newId);
    setIsCleanFinished(false);
    try {
      const data = await api.getDataset(newId);
      console.log("got dataset data:", data?.id, data?.name);
      setDs(data);
    } catch (err) {
      console.error("failed to get dataset:", err);
    }
    console.log("navigating to /clean...");
    navigate("/clean");
  };

  // If unauthenticated, show split-screen Auth page
  if (!token) {
    return <AuthPage onAuthSuccess={handleAuthSuccess} />;
  }

  return (
    <AppShell
      user={user}
      onSignOut={handleSignOut}
      dataset={ds}
      isCleanFinished={isCleanFinished}
    >
      <Routes>
        {/* Default route */}
        <Route path="/" element={<Navigate to={ds ? "/clean" : "/upload"} replace />} />

        {/* Step 1: Upload */}
        <Route
          path="/upload"
          element={<UploadPage onDatasetUploaded={handleDatasetUploaded} />}
        />

        {/* Step 2: Clean */}
        <Route
          path="/clean"
          element={
            ds ? (
              <CleanPage
                ds={ds}
                onRefresh={() => refresh(dsId)}
                onFinishCleaning={() => {
                  if (dsId) localStorage.setItem(`dp_clean_done_${dsId}`, "true");
                  setIsCleanFinished(true);
                  navigate("/dashboard");
                }}
              />
            ) : dsId ? (
              <div className="flex items-center justify-center h-full py-20 text-[#475467]">
                <span className="text-sm font-medium">Loading dataset...</span>
              </div>
            ) : (
              <Navigate to="/upload" replace />
            )
          }
        />

        {/* Step 3: Dashboard */}
        <Route
          path="/dashboard"
          element={
            ds ? (
              <DashboardPage
                ds={ds}
                onOpenClean={() => navigate("/clean")}
              />
            ) : dsId ? (
              <div className="flex items-center justify-center h-full py-20 text-[#475467]">
                <span className="text-sm font-medium">Loading dataset...</span>
              </div>
            ) : (
              <Navigate to="/upload" replace />
            )
          }
        />

        {/* Fallback to /upload */}
        <Route path="*" element={<Navigate to="/upload" replace />} />
      </Routes>
    </AppShell>
  );
}

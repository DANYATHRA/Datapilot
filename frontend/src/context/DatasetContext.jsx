import { createContext, useContext, useCallback, useEffect, useState } from "react";
import { api } from "../api";

const DatasetContext = createContext(null);

export function DatasetProvider({ children, user }) {
  const [datasets, setDatasets] = useState([]);
  const [activeDatasetId, setActiveDatasetId] = useState(() => {
    return user ? localStorage.getItem(`dp_active_ds_${user}`) || "" : "";
  });
  const [loading, setLoading] = useState(true);

  const refreshDatasets = useCallback(async (preferredId) => {
    try {
      const list = await api("/datasets");
      setDatasets(list);
      setActiveDatasetId((curr) => {
        const target = preferredId || curr;
        if (list.some((d) => d.id === target)) {
          if (user) localStorage.setItem(`dp_active_ds_${user}`, target);
          return target;
        }
        const fallback = list[0]?.id || "";
        if (user) {
          if (fallback) localStorage.setItem(`dp_active_ds_${user}`, fallback);
          else localStorage.removeItem(`dp_active_ds_${user}`);
        }
        return fallback;
      });
    } catch {
      setDatasets([]);
      setActiveDatasetId("");
    } finally {
      setLoading(false);
    }
  }, [user]);

  const selectDataset = useCallback((id) => {
    setActiveDatasetId(id);
    if (user) {
      if (id) localStorage.setItem(`dp_active_ds_${user}`, id);
      else localStorage.removeItem(`dp_active_ds_${user}`);
    }
  }, [user]);

  useEffect(() => {
    if (user) {
      refreshDatasets();
    } else {
      setDatasets([]);
      setActiveDatasetId("");
      setLoading(false);
    }
  }, [user, refreshDatasets]);

  const activeDataset = datasets.find((d) => d.id === activeDatasetId) || null;
  const hasDataset = datasets.length > 0 && !!activeDataset;

  return (
    <DatasetContext.Provider
      value={{
        datasets,
        activeDataset,
        activeDatasetId,
        selectDataset,
        refreshDatasets,
        hasDataset,
        loading,
      }}
    >
      {children}
    </DatasetContext.Provider>
  );
}

export function useDataset() {
  const ctx = useContext(DatasetContext);
  if (!ctx) {
    throw new Error("useDataset must be used within a DatasetProvider");
  }
  return ctx;
}

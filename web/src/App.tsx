import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "./api/client";
import type { HealthResponse } from "./api/types";
import { config } from "./config";

type BackendState =
  | { kind: "checking" }
  | { kind: "online"; health: HealthResponse }
  | { kind: "offline"; message: string };

function App() {
  const [backend, setBackend] = useState<BackendState>({ kind: "checking" });

  const checkBackend = useCallback(async () => {
    setBackend({ kind: "checking" });
    try {
      setBackend({ kind: "online", health: await api.health() });
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Unexpected error";
      setBackend({ kind: "offline", message });
    }
  }, []);

  useEffect(() => {
    void checkBackend();
  }, [checkBackend]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>MiniDrive</h1>
      </header>
      <main className="app-main">
        <p className="muted">Backend: {config.apiBaseUrl}</p>
        <p className={`status status-${backend.kind}`}>
          {backend.kind === "checking" && "Checking backend…"}
          {backend.kind === "online" &&
            `Backend status: ${backend.health.status} (v${backend.health.version}, ${backend.health.environment})`}
          {backend.kind === "offline" && `Backend unavailable: ${backend.message}`}
        </p>
        <button type="button" onClick={() => void checkBackend()} disabled={backend.kind === "checking"}>
          Check connection
        </button>
      </main>
    </div>
  );
}

export default App;

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { ToastProvider } from "./components/Toasts";
import { I18nProvider } from "./i18n/I18nProvider";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root element is missing");

createRoot(container).render(
  <StrictMode>
    <I18nProvider>
      <ToastProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </ToastProvider>
    </I18nProvider>
  </StrictMode>,
);

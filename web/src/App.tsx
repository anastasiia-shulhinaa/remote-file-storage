import { useCallback, useEffect, useRef, useState } from "react";
import { folderApi } from "./api/client";
import type { Folder, User } from "./api/types";
import { useAuth } from "./auth/AuthContext";
import { FolderTree } from "./components/FolderTree";
import { Icon } from "./components/Icon";
import { LanguageSwitch } from "./components/LanguageSwitch";
import { useToast } from "./components/Toasts";
import { useI18n } from "./i18n/I18nProvider";
import { useColumnSettings } from "./lib/columns";
import { describeError } from "./lib/errors";
import { navigate, routeHref, useRoute } from "./lib/router";
import { AuthPage } from "./pages/AuthPage";
import { DrivePage } from "./pages/DrivePage";
import { SyncPage } from "./pages/SyncPage";

export function App() {
  const route = useRoute();
  const { user } = useAuth();

  const isAuthRoute = route.name === "login" || route.name === "register";

  // protected pages require a session; logged-in users skip the auth pages
  useEffect(() => {
    if (!user && !isAuthRoute) navigate({ name: "login" });
    if (user && isAuthRoute) navigate({ name: "drive", folderId: null });
  }, [user, isAuthRoute]);

  if (!user) {
    return <AuthPage mode={route.name === "register" ? "register" : "login"} />;
  }
  // keyed by user: another account never sees the previous user's column settings
  return <Workspace key={user.id} user={user} />;
}

function Workspace({ user }: { user: User }) {
  const route = useRoute();
  const { logout } = useAuth();
  const { t } = useI18n();
  const toast = useToast();
  const [folders, setFolders] = useState<Folder[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const columnSettings = useColumnSettings(user.id);

  const reloadFolders = useCallback(async () => {
    try {
      setFolders(await folderApi.list());
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, []);

  useEffect(() => {
    void reloadFolders();
  }, [reloadFolders]);

  // column settings that cannot reach the server are kept locally; say so once per problem
  const reportedProblem = useRef<string | null>(null);
  useEffect(() => {
    const problem = columnSettings.problem;
    if (problem && reportedProblem.current !== problem) {
      toast.error(t(problem === "save" ? "columns.savedLocally" : "columns.loadFailed"));
    }
    reportedProblem.current = problem;
  }, [columnSettings.problem, toast, t]);

  const rootId = user.root_folder_id ?? folders?.find((f) => f.parent_folder_id === null)?.id ?? null;
  const activeFolderId = route.name === "drive" ? (route.folderId ?? rootId) : null;
  const closeMenu = () => setMenuOpen(false);

  async function onLogout() {
    await logout();
    toast.info(t("auth.loggedOut"));
  }

  const initials = (user.display_name || user.email).slice(0, 1).toUpperCase();

  return (
    <div className={`shell ${menuOpen ? "menu-open" : ""}`}>
      <aside className="sidebar" aria-label={t("nav.navigation")}>
        <a className="brand" href={routeHref({ name: "drive", folderId: null })} onClick={closeMenu}>
          <span className="brand-mark">
            <Icon name="cloud" size={20} />
          </span>
          {t("app.name")}
        </a>

        <nav className="nav">
          <a
            href={routeHref({ name: "drive", folderId: null })}
            className={route.name === "drive" ? "active" : ""}
            onClick={closeMenu}
          >
            <Icon name="hardDrive" /> {t("nav.myDrive")}
          </a>
          <a href={routeHref({ name: "sync" })} className={route.name === "sync" ? "active" : ""} onClick={closeMenu}>
            <Icon name="sync" /> {t("nav.sync")}
          </a>
        </nav>

        <div className="sidebar-section">
          <div className="sidebar-label">{t("nav.folders")}</div>
          {folders ? (
            <FolderTree folders={folders} activeId={activeFolderId} onNavigate={closeMenu} />
          ) : (
            <div className="skeleton-list" aria-label={t("app.loading")}>
              <div className="skeleton line" />
              <div className="skeleton line short" />
            </div>
          )}
        </div>
      </aside>
      <div className="scrim" onClick={closeMenu} />

      <div className="main-column">
        <header className="topbar">
          <button
            className="icon-button menu-button"
            onClick={() => setMenuOpen((o) => !o)}
            aria-label={t("nav.openMenu")}
          >
            <Icon name="menu" />
          </button>
          <div className="topbar-spacer" />
          <LanguageSwitch />
          <div className="user-chip" title={user.email}>
            <span className="avatar">{initials}</span>
            <span className="user-text">
              <strong>{user.display_name}</strong>
              <small>{user.username ? `@${user.username}` : user.email}</small>
            </span>
          </div>
          <button className="button ghost compact" onClick={() => void onLogout()}>
            <Icon name="logout" size={16} /> <span className="hide-sm">{t("auth.logout")}</span>
          </button>
        </header>

        <main className="main">
          {error !== null && (
            <div className="alert alert-error">
              <Icon name="alert" /> {describeError(t, error)}
              <button className="button ghost compact" onClick={() => void reloadFolders()}>
                {t("drive.retry")}
              </button>
            </div>
          )}
          {!folders || !rootId ? (
            error === null && (
              <div className="page" aria-label={t("app.loading")}>
                <div className="skeleton title" />
                <div className="skeleton block" />
              </div>
            )
          ) : route.name === "sync" ? (
            <SyncPage folders={folders} defaultFolderId={rootId} onSynced={reloadFolders} />
          ) : (
            <DrivePage
              key={activeFolderId ?? rootId}
              folders={folders}
              folderId={activeFolderId ?? rootId}
              reloadFolders={reloadFolders}
              columnSettings={columnSettings}
            />
          )}
        </main>
      </div>
    </div>
  );
}

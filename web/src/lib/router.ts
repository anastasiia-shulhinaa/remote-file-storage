import { useEffect, useState } from "react";

// Minimal hash router: #/login, #/register, #/drive/<folderId>, #/sync.
// Hash URLs need no server-side fallback, so FastAPI can serve the build as plain static files.

export type Route =
  | { name: "login" }
  | { name: "register" }
  | { name: "drive"; folderId: string | null }
  | { name: "sync" };

export function parseRoute(hash: string): Route {
  const [first, second] = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  switch (first) {
    case "login":
      return { name: "login" };
    case "register":
      return { name: "register" };
    case "sync":
      return { name: "sync" };
    default:
      return { name: "drive", folderId: first === "drive" && second ? second : null };
  }
}

export function routeHref(route: Route): string {
  switch (route.name) {
    case "drive":
      return route.folderId ? `#/drive/${encodeURIComponent(route.folderId)}` : "#/drive";
    default:
      return `#/${route.name}`;
  }
}

export function navigate(route: Route): void {
  window.location.hash = routeHref(route);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const update = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

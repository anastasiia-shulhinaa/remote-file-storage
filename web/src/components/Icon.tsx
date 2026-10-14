import type { SVGProps } from "react";

// Small inline icon set (24×24, stroke-based) — no icon dependency needed.
const PATHS = {
  cloud: "M7 18a4.5 4.5 0 0 1-.6-8.96A6.5 6.5 0 0 1 18.9 8.5 4.75 4.75 0 0 1 18.25 18H7z",
  folder: "M3 7.5A1.5 1.5 0 0 1 4.5 6h4.38l2 2h8.62A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z",
  folderPlus:
    "M3 7.5A1.5 1.5 0 0 1 4.5 6h4.38l2 2h8.62A1.5 1.5 0 0 1 21 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5zM12 11v5M9.5 13.5h5",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  code: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5M10 12l-2 2 2 2M14 12l2 2-2 2",
  image: "M5 4h14a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1zM4 16l4.5-4.5 3.5 3.5 2.5-2.5L20 18M15.5 9.5h.01",
  upload: "M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  download: "M12 4v12M7 11l5 5 5-5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  sync: "M20 11a8 8 0 0 0-14.9-3.5M4 4v4h4M4 13a8 8 0 0 0 14.9 3.5M20 20v-4h-4",
  history: "M3 12a9 9 0 1 0 3-6.7M3 4v4h4M12 7v5l3 2",
  plus: "M12 5v14M5 12h14",
  chevronRight: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  columns: "M4 5h16v14H4zM9.5 5v14M14.5 5v14",
  arrowUp: "M12 19V5M6 11l6-6 6 6",
  arrowDown: "M12 5v14M6 13l6 6 6-6",
  logout: "M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l5-5-5-5M15 12H4",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  laptop: "M4 6a1 1 0 0 1 1-1h14a1 1 0 0 1 1 1v9H4zM2 18h20",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  menu: "M4 6h16M4 12h16M4 18h16",
  filter: "M4 5h16l-6 7.5V19l-4-2v-4.5z",
  equal: "M5 9h14M5 15h14",
  hardDrive: "M3 13h18v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1zM5.5 5h13l2.5 8H3zM7 16h.01M11 16h.01",
  eraser: "M8 20h12M4.6 13.6l8.8-8.8a2 2 0 0 1 2.8 0l3 3a2 2 0 0 1 0 2.8L12 17.8 8.2 20H6.8l-2.2-2.2a2 2 0 0 1 0-2.8zM9 9.2l5.8 5.8",
  eyeOff: "M3 3l18 18M10.6 5.1A9.8 9.8 0 0 1 12 5c6.5 0 10 7 10 7a17.6 17.6 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2 12 2 12s3.5 7 10 7a9.4 9.4 0 0 0 4.3-1M9.9 9.9a3 3 0 0 0 4.2 4.2",
} as const;

export type IconName = keyof typeof PATHS;

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 18, ...rest }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export function fileIcon(extension: string): { icon: IconName; tone: string } {
  switch (extension.toLowerCase()) {
    case ".c":
    case ".cpp":
    case ".h":
    case ".hpp":
    case ".py":
    case ".ts":
    case ".js":
    case ".java":
      return { icon: "code", tone: "tone-code" };
    case ".png":
    case ".jpg":
    case ".jpeg":
    case ".jfif":
    case ".jpe":
    case ".bmp":
    case ".gif":
    case ".svg":
    case ".webp":
      return { icon: "image", tone: "tone-image" };
    default:
      return { icon: "file", tone: "tone-file" };
  }
}

// Relative-path safety for local filesystem operations.
// The backend validates manifests too; this check guards the browser side:
// a plan entry can never reach outside the folder the user picked.

import { CodedError } from "../lib/errors";

const FORBIDDEN = /[\\:*?"<>|\u0000-\u001f]/;

export function splitRelativePath(path: string): string[] {
  if (!path || path.startsWith("/") || /^[A-Za-z]:/.test(path)) {
    throw new CodedError("unsafe_path", `Unsafe path: ${JSON.stringify(path)}`);
  }
  const segments = path.split("/");
  for (const segment of segments) {
    if (!segment || segment === "." || segment === ".." || FORBIDDEN.test(segment)) {
      throw new CodedError("unsafe_path", `Unsafe path: ${JSON.stringify(path)}`);
    }
  }
  return segments;
}

/** "labs/lab1/main.cpp" → { dirs: ["labs","lab1"], name: "main.cpp" } */
export function splitParent(path: string): { dirs: string[]; name: string } {
  const segments = splitRelativePath(path);
  const name = segments.pop() as string;
  return { dirs: segments, name };
}

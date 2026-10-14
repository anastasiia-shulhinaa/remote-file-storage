// A short, non-identifying description of this browser for the synchronization history,
// e.g. "Edge · Windows". Only the browser family and the OS family: no versions, no ids.

function browserName(ua: string): string {
  if (/Edg\//.test(ua)) return "Edge";
  if (/OPR\/|Opera/.test(ua)) return "Opera";
  if (/Firefox\//.test(ua)) return "Firefox";
  if (/Chrome\//.test(ua)) return "Chrome";
  if (/Safari\//.test(ua)) return "Safari";
  return "Browser";
}

function osName(ua: string): string {
  if (/Windows/.test(ua)) return "Windows";
  if (/Android/.test(ua)) return "Android";
  if (/iPhone|iPad|iOS/.test(ua)) return "iOS";
  if (/Mac OS X|Macintosh/.test(ua)) return "macOS";
  if (/CrOS/.test(ua)) return "ChromeOS";
  if (/Linux/.test(ua)) return "Linux";
  return "";
}

export function deviceLabel(ua: string = navigator.userAgent): string {
  const os = osName(ua);
  return os ? `${browserName(ua)} · ${os}` : browserName(ua);
}

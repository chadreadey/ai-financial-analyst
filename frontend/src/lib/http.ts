// vercel.json rewrites unknown paths to index.html, so a missing file can be 200 HTML.
export function isJson(res: Response): boolean {
  return (res.headers.get("content-type") ?? "").includes("application/json");
}

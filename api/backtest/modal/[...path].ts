// Vercel Function — proxies /api/backtest/modal/* to Railway with X-API-Key.
// Runs on Vercel's Node runtime (Fluid Compute). No client-side secret exposure.

const BACKEND_URL = process.env.RAILWAY_BACKEND_URL;
const API_KEY = process.env.INTERNAL_API_KEY;

export default async function handler(req: Request): Promise<Response> {
  if (!BACKEND_URL || !API_KEY) {
    return Response.json(
      { error: "proxy misconfigured: set RAILWAY_BACKEND_URL and INTERNAL_API_KEY" },
      { status: 500 },
    );
  }

  const url = new URL(req.url);
  const segments = url.pathname.split("/api/backtest/modal")[1] ?? "";
  const target = `${BACKEND_URL}/api/backtest/modal${segments}${url.search}`;

  const headers: Record<string, string> = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
  };

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const body = hasBody ? await req.text() : undefined;

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body,
  });

  const respHeaders = new Headers();
  const ct = upstream.headers.get("content-type");
  if (ct) respHeaders.set("content-type", ct);

  return new Response(upstream.body, {
    status: upstream.status,
    headers: respHeaders,
  });
}

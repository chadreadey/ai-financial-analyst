import { useSearchParams } from "react-router-dom";

// Placeholder; replaced in Task 5.
export function LiveRunPage() {
  const [params] = useSearchParams();
  return <h1 className="text-xl font-bold">Live run: {params.get("ticker")}</h1>;
}

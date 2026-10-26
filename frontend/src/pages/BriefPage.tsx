import { useParams } from "react-router-dom";

// Placeholder; replaced in Task 5.
export function BriefPage() {
  const { ticker } = useParams();
  return <h1 className="text-xl font-bold">Brief: {ticker}</h1>;
}

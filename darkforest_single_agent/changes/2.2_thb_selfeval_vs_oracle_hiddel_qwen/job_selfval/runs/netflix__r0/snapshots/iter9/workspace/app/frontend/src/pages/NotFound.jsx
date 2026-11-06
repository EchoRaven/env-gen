import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-nfg flex flex-col items-center justify-center gap-4">
      <div className="font-display text-6xl">404</div>
      <div className="text-[#999]">Whoa! We can't find the page you're looking for.</div>
      <Link to="/browse" className="text-[#53c1de] hover:underline">Go to Home</Link>
    </div>
  );
}

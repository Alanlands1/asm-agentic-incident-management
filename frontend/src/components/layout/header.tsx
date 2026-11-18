import Link from "next/link";
import { ShieldCheck, ShieldAlert, BookOpen, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";

export function Header() {
  return (
    <header className="sticky top-0 z-40 border-b border-[#e0e1dc] bg-white/95 backdrop-blur-md">
      <div className="max-w-[96rem] mx-auto px-6 h-15 flex items-center justify-between">
        <div className="flex items-center gap-8">
          <Link href="/" className="flex items-center gap-3 font-semibold text-sm tracking-tight text-[#222222] hover:opacity-90 transition-opacity">
            <span className="flex h-7 w-7 items-center justify-center rounded bg-[#a20a29] text-white font-sans text-xs font-bold shadow-xs">
              CL
            </span>
            <div className="flex flex-col leading-tight">
              <span className="text-sm font-semibold tracking-tight text-[#222222]">AMS Incident Intelligence</span>
              <span className="text-[11px] text-[#5e605d]">Enterprise Agentic Console</span>
            </div>
          </Link>

          <nav className="hidden md:flex items-center gap-1 text-xs font-medium">
            <Link
              href="/"
              className="px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              Overview
            </Link>
            <Link
              href="/tickets"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              <span>Tickets</span>
            </Link>
            <Link
              href="/dq-rules"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              <ShieldCheck className="h-3.5 w-3.5 text-[#a20a29]" />
              <span>01 Data Quality</span>
            </Link>
            <Link
              href="/triage"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              <ShieldAlert className="h-3.5 w-3.5 text-[#005656]" />
              <span>02 Triage</span>
            </Link>
            <Link
              href="/resolution"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              <BookOpen className="h-3.5 w-3.5 text-[#b08824]" />
              <span>03 Resolution</span>
            </Link>
            <a
              href="http://localhost:8000/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-[#5e605d] hover:text-[#222222] hover:bg-[#f0f4f4] transition-colors"
            >
              <FileText className="h-3.5 w-3.5 text-[#5e605d]" />
              API Specs
            </a>
          </nav>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-2 text-xs text-[#5e605d] border border-[#e0e1dc] px-2.5 py-1 rounded-md bg-[#fbfbfb]">
            <span className="inline-block h-2 w-2 rounded-full bg-[#005656]" />
            <span>Operational</span>
          </div>
          <Badge className="bg-[#a20a29] hover:bg-[#850821] text-white text-xs font-medium px-2.5 py-0.5 border-none">
            Production
          </Badge>
        </div>
      </div>
    </header>
  );
}

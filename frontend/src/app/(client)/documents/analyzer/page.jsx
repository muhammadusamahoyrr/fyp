import { redirect } from "next/navigation";

/* The Document Analyzer is a lawyer's tool (2026-10-03): a client account has
 * no analyzer. An old link or bookmark lands on Documents instead. */
export default function Page() {
    redirect("/documents");
}

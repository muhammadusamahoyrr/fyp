import { redirect } from "next/navigation";
import { lawyerReviewRequestDeepLink } from "@/lib/reviewRequests.js";

/* The lawyer notification deep link (DOCUMENT_REVIEW_REQUEST_PLAN.md §6):
 * /lawyer/review-requests/{id} -> /lawyer/documents/review-queue?request={id}.
 * A fixed destination; the id is validated and passed only as a query value,
 * so this cannot redirect anywhere else. Whether the request exists and was
 * sent to this lawyer is the server's answer, on the Review Queue page. */
export default async function LawyerReviewRequestLink({ params }) {
    const { id } = await params;
    redirect(lawyerReviewRequestDeepLink(id));
}

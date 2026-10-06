import { redirect } from "next/navigation";
import { reviewRequestDeepLink } from "@/lib/reviewRequests.js";

/* The client notification deep link (DOCUMENT_REVIEW_REQUEST_PLAN.md §6):
 * /client/review-requests/{id} -> /documents?tab=review-requests&request={id}.
 * The destination is a fixed path; the id is validated and passed only as a
 * query value (see reviewRequestDeepLink), so this cannot redirect elsewhere.
 * Whether the request exists, and is the caller's, is decided by the Documents
 * page against the server -- never here. */
export default async function ReviewRequestLink({ params }) {
    const { id } = await params;
    redirect(reviewRequestDeepLink(id));
}

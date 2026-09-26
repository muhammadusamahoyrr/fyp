/* The lawyer drafter's starting points.
 *
 * WHY THE CATALOGUE IS THIS SHORT
 *
 * It advertised fourteen document types — NDA, sale deed, employment contract,
 * power of attorney, affidavit, RTI application, Vakalatnama and more — but only
 * two had a body of their own. The other twelve all opened the same generic
 * court-petition scaffold with the card's title pasted on top, so a lawyer who
 * picked "Property Sale Deed" got "IN THE COURT OF THE HONOURABLE JUDGE … PRAYER".
 * The Vakalatnama card was worse: the system deliberately has only an execution
 * CHECKLIST for that instrument (see the server catalogue), never the instrument.
 *
 * So the catalogue lists only what it actually has: the two starters with real
 * bodies, and one scaffold that says plainly it is generic. A document type
 * returns here when it has a body of its own — not before.
 *
 * Kept out of the component so it can be tested by import. */
import { escapeHtml } from "./escapeHtml.js";

export const BLANK_TEMPLATE = {
    id: 0,
    name: "Blank legal draft",
    cat: "General",
    desc: "A generic court-filing scaffold — introduction, facts, grounds, prayer. Not specific to any instrument; adapt it yourself.",
    icon: "📄",
    popular: false,
};

export const TEMPLATES = [
    { id: 1, name: "Dissolution of Marriage Application", cat: "Family", desc: "Starter petition under the Dissolution of Muslim Marriages Act, 1939 and MFLO 1961 — parties, marriage, grounds and prayer, with placeholders to complete.", icon: "⚖️", popular: true },
    { id: 2, name: "Plaint — Civil Suit", cat: "Litigation", desc: "Starter plaint under Order VII Rule 1 CPC — parties, facts, cause of action, jurisdiction and prayer, with placeholders to complete.", icon: "🏛️", popular: true },
    BLANK_TEMPLATE,
];

// Derived, so a category pill can never lead to an empty grid.
export const CATEGORIES = ["All", ...new Set(TEMPLATES.map(t => t.cat))];

export function buildContent(tmpl, caseObj) {
    const caseRef = escapeHtml(caseObj?.id || "[Case No.]");
    const clientRef = escapeHtml(caseObj?.client || "[Client Name]");
    const court = escapeHtml(caseObj?.court || "[Court Name]");
    const title = escapeHtml(tmpl?.name || BLANK_TEMPLATE.name);
    const today = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });

    const map = {
        1: `IN THE FAMILY COURT AT [LOCATION]\n\nSuit No. ______/2026\n\n${clientRef.toUpperCase()}, W/O [Husband's Name],\nResident of [Full Address], CNIC No. [__________],\n\n...Petitioner\n\nVERSUS\n\n[Respondent's Name], S/O [Father's Name],\nResident of [Full Address],\n\n...Respondent\n\n\nPETITION FOR DISSOLUTION OF MARRIAGE (DIVORCE)\nUNDER THE MUSLIM FAMILY LAWS ORDINANCE, 1961\n\nRespectfully Sheweth:\n\n1. That the petitioner and the respondent were duly married on [Date] at [Place] in accordance with Muslim personal law.\n\n2. That the respondent has treated the petitioner with cruelty and has failed to maintain the petitioner without reasonable cause.\n\n3. That the petitioner is entitled to seek dissolution of marriage under Section 2(ix) of the Dissolution of Muslim Marriages Act, 1939.\n\nPRAYER:\nIt is therefore respectfully prayed that this Honourable Court may be pleased to:\n(a) Grant decree of dissolution of marriage;\n(b) Award maintenance to the petitioner;\n(c) Award costs of the proceedings.\n\nDate: ${today}\n\n_________________________\nPetitioner / Advocate`,
        2: `IN THE COURT OF THE CIVIL JUDGE, LAHORE\n\nCase No. ${caseRef} of 2026\n\n${clientRef.toUpperCase()}\n...Plaintiff\n\nVERSUS\n\n[Defendant Name]\n...Defendant\n\n\nPLAINT UNDER ORDER VII RULE 1, C.P.C.\n\nMost Respectfully Sheweth:\n\n1. That the plaintiff is a resident of [Address] and is entitled to file the present suit.\n\n2. That the defendant is indebted to the plaintiff in the sum of PKR [Amount] on account of [cause of action].\n\n3. That the cause of action arose on [Date] when the defendant failed to honour the obligation despite written demand dated [Date].\n\n4. That this Court has territorial and pecuniary jurisdiction to try the present suit.\n\nPRAYER:\nThe plaintiff humbly prays that this Honourable Court may be pleased to:\n(a) Decree the suit for PKR [Amount];\n(b) Award markup at the rate of [Rate]% per annum;\n(c) Award costs of the suit.\n\nVerified: The contents of the above plaint are true to the best of my knowledge.\n\nDate: ${today}\t\t\t_______________________\n\t\t\t\t\tPlaintiff / Advocate`,
        default: `IN THE COURT OF [COURT]\n\nCase Reference: ${caseRef}\n\n${title.toUpperCase()}\n\nIN THE MATTER OF: ${clientRef}\n\nBefore: ${court}\n\nDate: ${today}\n\n${"─".repeat(60)}\n\n1. INTRODUCTION\n\n[Nature of this filing and on whose behalf it is made.]\n\n2. FACTS\n\nThe relevant facts are as follows:\n\n   a) [State first material fact]\n   b) [State second material fact]\n   c) [State third material fact]\n\n3. GROUNDS\n\n   i.  [Ground one — legal basis]\n   ii. [Ground two — factual basis]\n\n4. PRAYER\n\n[Relief sought.]\n\n${"─".repeat(60)}\n\nDate: ${today}\t\t\t_______________________\n\t\t\t\t\t[Advocate Name]\n\t\t\t\t\tBar Council Enrollment No.: [__________]`,
    };

    return map[tmpl?.id] || map.default;
}

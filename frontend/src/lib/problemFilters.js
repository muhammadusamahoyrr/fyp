/* Reads a client's own description of their problem ("mere bhai ne plot par
 * qabza kar liya hai, Lahore") into the directory's existing filters: an area
 * of law and a province. Runs in the browser; the text is never sent anywhere.
 *
 * It is a keyword reading, not legal advice and not a classifier: it only
 * chooses filters the client can see and undo. When nothing is recognised it
 * says so rather than guessing. English and Roman Urdu terms both count. */

// area value (as the server's PRACTICE_AREAS) -> words that point to it
const AREA_WORDS = {
    family: ["divorce", "talaq", "talak", "khula", "nikah", "nikkah", "marriage", "shadi", "husband", "shohar",
        "wife", "biwi", "custody", "guardian", "guardianship", "child", "bachay", "bacha", "haq mehr", "mehr",
        "dowry", "jahez", "maintenance", "nafqa", "nafaqa", "family court", "second marriage"],
    criminal: ["fir", "f.i.r", "bail", "zamanat", "police", "arrest", "giraftar", "griftar", "theft", "chori",
        "murder", "qatl", "robbery", "daketi", "dacoity", "kidnap", "agwa", "assault", "maar peet", "jail",
        "harassment", "blackmail", "threat", "dhamki", "challan", "acquittal", "criminal"],
    property: ["plot", "zameen", "zamin", "land", "house", "makan", "ghar", "flat", "shop", "dukaan", "qabza",
        "possession", "inheritance", "wirasat", "virasat", "warasat", "mutation", "intiqal", "inteqal", "fard",
        "registry", "sale deed", "bayana", "tenant", "kirayadar", "landlord", "rent", "kiraya", "partition",
        "taqseem", "property"],
    labour: ["salary", "tankhwah", "tankhah", "wages", "job", "naukri", "nokri", "employer", "employee",
        "terminated", "termination", "fired", "dismissal", "eobi", "gratuity", "overtime", "labour", "labor",
        "factory"],
    corporate: ["company", "secp", "shares", "shareholder", "director", "partnership", "partner", "business",
        "karobar", "startup", "incorporation", "trademark", "corporate"],
    civil: ["recovery", "qarza", "qarz", "loan", "debt", "money owed", "paisay wapis", "contract", "agreement",
        "muahida", "damages", "injunction", "stay order", "civil suit", "declaration", "specific performance"],
    constitutional: ["writ", "fundamental right", "constitution", "high court petition", "government department",
        "sarkari", "public servant", "service matter", "nab", "illegal detention", "constitutional"],
};

// city or province word -> the directory's province value
const PLACE_WORDS = {
    Punjab: ["punjab", "lahore", "rawalpindi", "pindi", "multan", "faisalabad", "gujranwala", "sialkot",
        "sargodha", "bahawalpur", "sahiwal", "sheikhupura", "gujrat", "jhelum", "kasur", "okara"],
    Sindh: ["sindh", "karachi", "hyderabad", "sukkur", "larkana", "nawabshah", "mirpurkhas"],
    KPK: ["kpk", "khyber", "pakhtunkhwa", "peshawar", "mardan", "abbottabad", "swat", "kohat", "bannu", "nowshera"],
    Balochistan: ["balochistan", "baluchistan", "quetta", "gwadar", "turbat", "khuzdar"],
    Federal: ["islamabad", "federal", "ict"],
};

const AREA_LABEL = {
    family: "Family", criminal: "Criminal", property: "Property", labour: "Employment",
    corporate: "Corporate", civil: "Civil", constitutional: "Constitutional",
};

function norm(text) {
    return ` ${String(text || "").toLowerCase().replace(/[^a-z0-9.\s]+/g, " ").replace(/\s+/g, " ")} `;
}

// whole word or phrase, so "fir" does not match "first"
function has(hay, word) {
    return hay.includes(` ${word} `);
}

function best(hay, table) {
    let top = null;
    let topHits = 0;
    for (const [key, words] of Object.entries(table)) {
        const hits = words.reduce((n, w) => n + (has(hay, w) ? 1 : 0), 0);
        if (hits > topHits) { top = key; topHits = hits; }
    }
    return top;
}

/** -> { area: "property"|null, areaLabel, province: "Punjab"|null } */
export function readProblem(text) {
    const hay = norm(text);
    const area = best(hay, AREA_WORDS);
    const province = best(hay, PLACE_WORDS);
    return { area, areaLabel: area ? AREA_LABEL[area] : null, province };
}

export const PROBLEM_MAX_LENGTH = 500;

"""Statute disambiguation for queries in everyday language.

The problem this solves
-----------------------
"Can a tenant be evicted without notice in Punjab?" retrieved the Punjab
Tenancy Act 1887 — which governs AGRICULTURAL tenancy, cultivators and land —
instead of the Punjab Rented Premises Act 2009, which governs houses and shops
and actually answers the question. The correct statute ranked sixth, losing by
1.5% of cosine similarity.

Both statutes are genuinely about tenants and eviction, so this is not a
vocabulary gap. It is an ambiguity between two laws that share a subject and
differ in scope, and it got WORSE as the corpus grew: ingesting provincial law
added a lexically similar competitor.

Why not just expand the query
-----------------------------
Measured. Appending statutory vocabulary ("rented premises eviction landlord")
raised the target's score from 0.845 to 0.860 but left it at rank 6, because the
competitors' scores rose too — adding words moves the whole embedding. On one
test query it made matters worse, pushing CrPC from rank 3 to rank 5.

What works instead
------------------
Read the SUBJECT of the query — house, shop, rent, deposit versus land, crop,
cultivation — and prefer the statute whose scope matches. Measured on the same
queries, the target moved from rank 6 to rank 1, while an explicitly
agricultural query correctly kept the Tenancy Act on top.

Adding rules
------------
Each rule is a claim about which law governs a situation, so VERIFY before
adding one: a wrong rule buries the correct statute, which is the failure this
module exists to prevent. Seeded with the single case that was measured.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Multipliers applied to a chunk's similarity. Deliberately modest: the intent
# is to break a near-tie between statutes of comparable relevance, not to
# override retrieval. A boost large enough to promote a genuinely poor match
# would trade one failure mode for another.
BOOST = 1.12
PENALTY = 0.88


@dataclass(frozen=True)
class TopicRule:
    name: str
    require: re.Pattern      # query must match this
    exclude: re.Pattern | None  # ...and must NOT match this
    prefer: frozenset[str] = field(default_factory=frozenset)
    demote: frozenset[str] = field(default_factory=frozenset)

    def applies(self, query: str) -> bool:
        if not self.require.search(query):
            return False
        return not (self.exclude and self.exclude.search(query))


RULES: list[TopicRule] = [
    TopicRule(
        name="urban tenancy",
        # A house, shop or rent relationship — the Rented Premises Act.
        require=re.compile(
            r"\b(rent|rented|rental|premises|landlord|tenant|evict|eviction|"
            r"deposit|lease|house|flat|apartment|shop|building|makan|kiraya)\b",
            re.IGNORECASE),
        # ...unless the query is plainly about farmland, which is the Tenancy Act.
        exclude=re.compile(
            r"\b(agricultur|crop|cultivat|land\s+revenue|kashtkar|zamindar|"
            r"harvest|occupancy|khata|khasra|mutation)\b", re.IGNORECASE),
        prefer=frozenset({"Punjab Rented Premises Act 2009"}),
        demote=frozenset({
            "Punjab Tenancy Act 1887",
            "Punjab Protection and Restoration of Tenancy Rights Act 1950",
            "Punjab Tenancy (Validation) Ordinance 1969",
            "Punjab Land Revenue Act 1967",
        }),
    ),
]


def statute_weight(query: str, statute: str) -> float:
    """Multiplier for a chunk of `statute` given `query`. 1.0 when no rule fires.

    Rules compose multiplicatively, so a statute preferred by one rule and
    demoted by another lands near neutral rather than having the last rule win.
    """
    if not query or not statute:
        return 1.0
    weight = 1.0
    for rule in RULES:
        if not rule.applies(query):
            continue
        if statute in rule.prefer:
            weight *= BOOST
        elif statute in rule.demote:
            weight *= PENALTY
    return weight


def active_rules(query: str) -> list[str]:
    """Names of the rules firing for this query — recorded in provenance so a
    ranking decision can be explained after the fact."""
    return [r.name for r in RULES if r.applies(query or "")]

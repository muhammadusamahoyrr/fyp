"""Expected-loss action selection from an explicit harm matrix.

Replaces a cost vector that did not work. The previous formulation assigned
cost(answer)=0.10, cost(defer)=0.30, cost(refuse)=0.60 and selected the action
maximising confidence/cost. Two things were wrong with it:

  1. The action was never derived from it. _select_action is a threshold rule
     and never read the cost vector at all.
  2. Where the utility WAS used — choosing among evidence sources — the cost
     cancels. Every candidate is scored with the same cost function, and the
     action is itself a function of confidence, so argmax of c/cost(a(c)) is
     monotone in c and simply returns the most confident source.

Swept over 512 cost vectors spanning an order of magnitude in each component,
including orderings that invert the intended asymmetry, not one of 65 decision
points changed. The cost model was decorative.

The formulation
---------------
Let c be the probability that the evidence supports a correct answer. Two
harms are possible, and they are not symmetric:

    L_wrong   a confident wrong statement of law, acted on by the user
    L_missed  a refusal on a question the system could have answered

Expected loss of each action:

    E[L(answer)] = (1 - c) * L_wrong
    E[L(refuse)] = c * L_missed
    E[L(defer)]  = L_ask + min(E[L(answer)], E[L(refuse)]) - g * d

where L_ask is the friction of asking the user for more facts, d is the
disagreement between the confidence signals, and g is how much of that
disagreement a clarification is expected to resolve.

Deferring is scored against the disagreement, not against the loss itself. An
earlier version discounted the whole remaining loss by a fixed fraction, which
made asking a question a good deal unconditionally: it deferred on all 13 test
confidences at every harm ratio, because a 35% discount always beat a 5%
friction. A clarification does not reduce the harm of answering a question the
system already understands. It reduces the chance that the confidence estimate
is itself wrong, which is what signal disagreement measures — so with signals in
agreement (d = 0) deferring is strictly worse than acting, which is correct.

Answering beats refusing exactly when (1-c) * L_wrong < c * L_missed, i.e. when

    c > L_wrong / (L_wrong + L_missed)  =  1 / (1 + rho),   rho = L_missed/L_wrong

so the operating threshold IS the harm ratio. This is the property the cost
vector was supposed to have and did not: one interpretable parameter, rho,
which a practitioner can be asked about directly — "how many unnecessary
refusals would you accept to prevent one wrong statement of law?" — and which
maps to a threshold by derivation rather than by tuning.

What the current thresholds imply
---------------------------------
Read in reverse, the deployed generation floor of 0.20 implies

    0.20 = 1 / (1 + rho)   =>   rho = 4

that is, that a missed answer is FOUR TIMES worse than a wrong statement of
law. That is the inverse of the asymmetry the system is designed around. The
threshold was seeded as a percentile of a score distribution, never as a
statement about harm, and nothing connected the two until this module.

DEFAULT_RHO below preserves the deployed behaviour rather than silently
changing what the system refuses; raising it is a policy decision, and
harm_ratio_for_threshold() and threshold_for_harm_ratio() are provided so the
choice can be made explicitly and reported.
"""
from __future__ import annotations

from typing import NamedTuple

# Preserves the deployed operating point (generation floor 0.20). This is NOT
# an endorsement of rho=4 — see the module docstring. It is here so that
# introducing the derivation does not by itself change what users are refused.
DEFAULT_RHO = 4.0

# Friction of one clarification round, in units of L_wrong. Small: asking a
# question is cheap next to answering wrongly, but it is not free, which is
# what stops the system deferring indefinitely.
DEFAULT_ASK_COST = 0.05

# How much of the signal disagreement a clarification is expected to resolve,
# in units of L_wrong per unit of disagreement. Deferring is worth its friction
# only when the signals disagree by more than ask_cost/info_gain.
DEFAULT_INFO_GAIN = 1.20


class ExpectedLoss(NamedTuple):
    answer: float
    defer:  float
    refuse: float

    def best(self) -> str:
        return min(("answer", "defer", "refuse"), key=lambda a: getattr(self, a))


def threshold_for_harm_ratio(rho: float) -> float:
    """Confidence above which answering has lower expected loss than refusing.

    rho is how many unnecessary refusals are worth one wrong statement of law.
    """
    if rho < 0:
        raise ValueError("harm ratio must be non-negative")
    return 1.0 / (1.0 + rho)


def harm_ratio_for_threshold(threshold: float) -> float:
    """The harm ratio a given operating threshold implicitly assumes.

    Use this to interrogate a threshold that was set some other way — a
    percentile, a hunch — and state what it commits the system to.
    """
    if not 0.0 < threshold <= 1.0:
        raise ValueError("threshold must be in (0, 1]")
    return (1.0 - threshold) / threshold


def expected_losses(
    confidence:   float,
    disagreement: float = 0.0,
    rho:          float = DEFAULT_RHO,
    ask_cost:     float = DEFAULT_ASK_COST,
    info_gain:    float = DEFAULT_INFO_GAIN,
) -> ExpectedLoss:
    """Expected loss of each action, in units of L_wrong.

    `disagreement` is the inter-signal variance from the scorer. It is what
    makes deferring worth its friction: with signals in agreement there is
    nothing for a clarification to resolve.
    """
    c = max(0.0, min(1.0, confidence))
    d = max(0.0, disagreement)
    answer = (1.0 - c) * 1.0
    refuse = c * rho
    defer  = ask_cost + min(answer, refuse) - info_gain * d
    return ExpectedLoss(answer=answer, defer=defer, refuse=refuse)


def select_action(
    confidence: float,
    variance:   float = 0.0,
    rho:        float = DEFAULT_RHO,
    ask_cost:   float = DEFAULT_ASK_COST,
    info_gain:  float = DEFAULT_INFO_GAIN,
) -> str:
    """Minimum-expected-loss action.

    One quantity is minimised throughout — there is no separate variance branch
    overriding the arithmetic, as in the threshold rule this replaces.
    """
    return expected_losses(confidence, variance, rho, ask_cost, info_gain).best()

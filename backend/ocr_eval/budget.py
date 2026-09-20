"""Budget reservation accounting for a metered experiment.

THE FAILURE THIS EXISTS TO PREVENT

A run that checks "have I spent too much?" after each response can overspend in two
ways, and both happen exactly when things are going wrong:

  * CONCURRENCY. Two calls in flight both pass a check the remaining budget covers
    only once. With retries amplifying each call, a ceiling can be passed several
    times over before any response arrives.
  * UNKNOWN USAGE. A call that times out or returns no usage metadata was very
    likely processed and billed. Treating missing usage as zero understates spend
    precisely when a run is failing and retrying.

So cost is RESERVED before dispatch, at worst case including permitted retries, and
a reservation is released only when the call is settled. An unsettled call keeps its
reservation as `unknown_exposure`, which is reported beside `confirmed_cost` and
never summed into a single headline figure -- one is measured, the other is a
worst-case estimate, and adding them produces a number that is neither.

No provider is contacted from this module. It is arithmetic and bookkeeping.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field

#: Prices are quoted per million tokens. Every conversion goes through this one
#: constant: a stray 1_000 somewhere is a 1000x accounting error, and a budget
#: module that is wrong by three orders of magnitude is worse than no budget.
TOKENS_PER_PRICE_UNIT = 1_000_000


#: Reported when an attempt's ACTUAL usage exceeded what was reserved for it.
#: A conservative pre-dispatch estimate can still be wrong; when it is, the run
#: says so instead of quietly passing the approved figure.
BUDGET_ESTIMATE_BREACH = "BUDGET_ESTIMATE_BREACH"


class BudgetError(RuntimeError):
    """Misuse of the ledger, or an input it cannot price."""


class BudgetExceeded(BudgetError):
    """Raised when a reservation cannot be made within the approved ceiling."""


def _check_money(value: float, what: str) -> float:
    """A price or ceiling has to be a finite, non-negative number.

    A NaN ceiling ACCEPTED EVERY RESERVATION, because `committed + amount > nan`
    is False like every other NaN comparison. A budget that cannot be exceeded is
    not a budget, and the failure is silent at exactly the moment it matters.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number, got {value!r}")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{what} must be finite and non-negative, got {value!r}")
    return float(value)


def _check_tokens(value: int, what: str) -> int:
    """Token counts are non-negative whole numbers, and nothing else.

    NaN and infinity priced to NaN and infinity; a negative count priced to a
    NEGATIVE cost, which would have credited the budget for work that was done.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a number, got {value!r}")
    if not math.isfinite(value) or value < 0 or value != int(value):
        raise ValueError(
            f"{what} must be a non-negative whole number, got {value!r}")
    return int(value)


@dataclass(frozen=True)
class Prices:
    """USD per million tokens, as quoted by the provider's pricing page."""
    input_per_million: float
    output_per_million: float

    def __post_init__(self):
        _check_money(self.input_per_million, "input_per_million")
        _check_money(self.output_per_million, "output_per_million")

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        inp = _check_tokens(input_tokens, "input_tokens")
        out = _check_tokens(output_tokens, "output_tokens")
        return (
            (inp / TOKENS_PER_PRICE_UNIT) * self.input_per_million
            + (out / TOKENS_PER_PRICE_UNIT) * self.output_per_million
        )


@dataclass
class Reservation:
    """One call's budget, from reservation through every attempt it makes.

    A call is not one billable event. It is up to `max_attempts` of them, each
    with its own token usage, and any of them can time out having been processed
    and charged. So the attempts are recorded individually rather than inferred
    from a count.
    """
    call_id: str
    reserved: float
    attempts: int
    #: What was sent. Kept so an attempt that returns NO usage can still be
    #: charged for the input it certainly transmitted.
    input_tokens: int = 0
    recorded_attempts: int = 0
    dispatched: bool = False
    settled: bool = False
    #: Cost of attempts whose usage the provider actually reported.
    confirmed: float = 0.0
    #: Worst-case cost of attempts that returned no usage. RETAINED after the
    #: call settles -- a later attempt succeeding does not un-bill an earlier one
    #: that timed out.
    unknown: float = 0.0
    unknown_attempts: int = 0
    #: Set when recorded cost passed the reservation taken before dispatch.
    estimate_breached: bool = False
    reasons: list[str] = field(default_factory=list)


@dataclass
class BudgetLedger:
    """Reserve-before-dispatch accounting against an approved ceiling.

    Thread-safe: reservations are taken under a lock so two concurrent callers
    cannot both pass a check the remaining budget covers once.

    A CALL IS NOT ONE BILLABLE EVENT. It is up to `max_attempts` of them, so
    attempts are recorded one at a time with their own usage. Charging N copies
    of one attempt's usage was wrong in both directions, and a retry storm --
    where attempt sizes differ most -- is exactly when it would have been most
    wrong.
    """
    ceiling_usd: float
    prices: Prices
    max_output_tokens: int
    max_attempts: int = 3          # 1 initial + 2 retries

    _calls: dict[str, Reservation] = field(default_factory=dict)
    _closed: list[Reservation] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        _check_money(self.ceiling_usd, "ceiling_usd")
        _check_tokens(self.max_output_tokens, "max_output_tokens")
        # A zero or fractional attempt budget makes `worst_case` zero or
        # nonsensical, and a reservation that costs nothing stops the ceiling
        # binding at all.
        if (isinstance(self.max_attempts, bool)
                or not isinstance(self.max_attempts, int)
                or self.max_attempts < 1):
            raise ValueError(
                f"max_attempts must be a positive whole number, "
                f"got {self.max_attempts!r}")

    # ── accounting views ────────────────────────────────────────────────────

    def _all(self) -> list[Reservation]:
        return list(self._calls.values()) + self._closed

    @property
    def confirmed_cost(self) -> float:
        """Spend backed by usage the provider actually reported."""
        return sum(r.confirmed for r in self._all())

    @property
    def unknown_exposure(self) -> float:
        """Worst-case cost of attempts that never returned usage.

        SURVIVES THE CALL SETTLING. A timed-out attempt was probably processed
        and charged, and a later attempt of the same call succeeding says nothing
        about it. Dropping it at settle time is how a run that timed out twice
        and succeeded on the third try reported one attempt's cost.
        """
        return sum(r.unknown for r in self._all())

    @property
    def outstanding_reserved(self) -> float:
        """Headroom still held for calls that have not settled."""
        return sum(max(0.0, r.reserved - r.confirmed - r.unknown)
                   for r in self._calls.values() if not r.settled)

    @property
    def committed(self) -> float:
        """What the ceiling is enforced against."""
        return self.confirmed_cost + self.unknown_exposure + self.outstanding_reserved

    @property
    def remaining(self) -> float:
        return self.ceiling_usd - self.committed

    @property
    def unreconciled_calls(self) -> int:
        return sum(1 for r in self._all() if r.unknown > 0)

    @property
    def estimate_breached(self) -> bool:
        """Did any call cost more than was reserved for it?"""
        return any(r.estimate_breached for r in self._all())

    # ── the reserve / attempt / settle cycle ────────────────────────────────

    def worst_case(self, input_tokens: int) -> float:
        """Cost if this call uses every permitted attempt and the full output cap."""
        return self.prices.cost(input_tokens, self.max_output_tokens) * self.max_attempts

    def _require(self, call_id: str) -> Reservation:
        reservation = self._calls.get(call_id)
        if reservation is None:
            raise KeyError(f"no open reservation for {call_id}")
        return reservation

    def _require_attempt_headroom(self, reservation: Reservation) -> None:
        """The reservation covers `max_attempts` and no more.

        Recording a further attempt spends budget that was never reserved, which
        is precisely how a retry loop escapes the ceiling it was supposed to be
        bounded by.
        """
        if reservation.recorded_attempts >= reservation.attempts:
            raise BudgetError(
                f"{reservation.call_id} has already recorded "
                f"{reservation.recorded_attempts} of {reservation.attempts} "
                f"reserved attempts")

    def reserve(self, call_id: str, input_tokens: int) -> Reservation:
        """Reserve worst-case cost BEFORE dispatch. Raises if it would exceed."""
        amount = self.worst_case(input_tokens)
        with self._lock:
            if call_id in self._calls or any(r.call_id == call_id for r in self._closed):
                raise BudgetError(f"call_id already used: {call_id}")
            if self.committed + amount > self.ceiling_usd:
                raise BudgetExceeded(
                    f"reserving {amount:.6f} would exceed ceiling "
                    f"{self.ceiling_usd:.6f} (committed {self.committed:.6f})")
            reservation = Reservation(call_id=call_id, reserved=amount,
                                      attempts=self.max_attempts,
                                      input_tokens=_check_tokens(
                                          input_tokens, "input_tokens"))
            self._calls[call_id] = reservation
            return reservation

    def mark_dispatched(self, call_id: str) -> None:
        """The request has left the process. From here it may have been billed."""
        with self._lock:
            self._require(call_id).dispatched = True

    def record_attempt(self, call_id: str, *, input_tokens: int,
                       output_tokens: int) -> float:
        """One attempt, priced on ITS OWN usage."""
        cost = self.prices.cost(input_tokens, output_tokens)
        with self._lock:
            reservation = self._require(call_id)
            self._require_attempt_headroom(reservation)
            reservation.dispatched = True
            reservation.recorded_attempts += 1
            reservation.confirmed += cost
            if reservation.confirmed + reservation.unknown > reservation.reserved:
                reservation.estimate_breached = True
            return cost

    def record_unknown_attempt(self, call_id: str,
                               reason: str = "no usage returned") -> float:
        """One attempt that returned no usage. Charged at worst case, and KEPT.

        This is the timeout case. The request very likely reached the provider
        and was billed, so its worst-case cost stays on the books until a human
        reconciles it against the provider's own usage console.
        """
        with self._lock:
            reservation = self._require(call_id)
            self._require_attempt_headroom(reservation)
            # ESTIMATED INPUT + MAXIMUM OUTPUT. The exposure was `cost(0, cap)`,
            # which ignored the prompt -- and for an OCR call the page image IS
            # the cost. Charging output alone understated a timed-out attempt by
            # most of its value.
            per_attempt = self.prices.cost(reservation.input_tokens,
                                           self.max_output_tokens)
            reservation.dispatched = True
            reservation.recorded_attempts += 1
            reservation.unknown += per_attempt
            reservation.unknown_attempts += 1
            reservation.reasons.append(reason)
            return per_attempt

    def settle(self, call_id: str) -> float:
        """Close the call, releasing only the UNUSED reservation headroom.

        Anything recorded stays recorded: confirmed attempts stay confirmed, and
        unknown attempts stay as exposure.
        """
        with self._lock:
            reservation = self._require(call_id)
            if reservation.settled:
                raise BudgetError(f"already settled: {call_id}")
            reservation.settled = True
            del self._calls[call_id]
            self._closed.append(reservation)
            return reservation.confirmed

    def reconcile_unknown(self, call_id: str, *, input_tokens: int,
                          output_tokens: int) -> float:
        """Resolve a call's unknown attempts from out-of-band usage data."""
        cost = self.prices.cost(input_tokens, output_tokens)
        with self._lock:
            for reservation in self._all():
                if reservation.call_id != call_id:
                    continue
                if reservation.unknown <= 0:
                    raise BudgetError(f"nothing unknown to reconcile for {call_id}")
                reservation.unknown = 0.0
                reservation.unknown_attempts = 0
                reservation.confirmed += cost
                return cost
        raise KeyError(f"no reservation for {call_id}")

    def release(self, call_id: str) -> None:
        """Release a reservation for a call that PROVABLY never dispatched.

        REFUSES once the request may have left the process. Releasing a possibly
        dispatched call frees budget for work that might already have been paid
        for, and leaves no record that the call ever existed -- which is the one
        thing a ledger must never do.
        """
        with self._lock:
            reservation = self._require(call_id)
            if reservation.dispatched:
                raise BudgetError(
                    f"{call_id} may have been dispatched; settle it instead of "
                    f"releasing it")
            del self._calls[call_id]

    # ── reporting ───────────────────────────────────────────────────────────

    def as_report_dict(self) -> dict:
        """Two figures, never one. A run with unknown exposure is ESTIMATED."""
        # OPEN WORK IS NOT A FINAL NUMBER. `FINAL` meant only "nothing
        # unreconciled", which is true before a single call has settled -- so a
        # run still in flight reported a total that invited being quoted as one.
        if self.estimate_breached:
            status = BUDGET_ESTIMATE_BREACH
        elif self._calls:
            status = "INCOMPLETE"
        elif self.unreconciled_calls:
            status = "ESTIMATED"
        else:
            status = "FINAL"
        final = status == "FINAL"
        return {
            "ceiling_usd": self.ceiling_usd,
            "confirmed_cost": round(self.confirmed_cost, 6),
            "unknown_exposure": round(self.unknown_exposure, 6),
            "outstanding_reserved": round(self.outstanding_reserved, 6),
            "committed": round(self.committed, 6),
            "remaining": round(self.remaining, 6),
            "calls_settled": len(self._closed),
            "calls_open": len(self._calls),
            "calls_unreconciled": self.unreconciled_calls,
            "estimate_breach": self.estimate_breached,
            "status": status,
            "note": (
                "All attempts reconciled." if final else
                "Actual usage exceeded its reservation; dispatch stopped."
                if status == BUDGET_ESTIMATE_BREACH else
                "Calls are still open; this is not a total." if status == "INCOMPLETE" else
                "Attempts that returned no usage keep their worst-case charge. "
                "Spend is an estimate until checked against the provider's own "
                "usage console."
            ),
        }

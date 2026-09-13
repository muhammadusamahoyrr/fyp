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

import threading
from dataclasses import dataclass, field

#: Prices are quoted per million tokens. Every conversion goes through this one
#: constant: a stray 1_000 somewhere is a 1000x accounting error, and a budget
#: module that is wrong by three orders of magnitude is worse than no budget.
TOKENS_PER_PRICE_UNIT = 1_000_000


class BudgetExceeded(RuntimeError):
    """Raised when a reservation cannot be made within the approved ceiling."""


@dataclass(frozen=True)
class Prices:
    """USD per million tokens, as quoted by the provider's pricing page."""
    input_per_million: float
    output_per_million: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            (input_tokens / TOKENS_PER_PRICE_UNIT) * self.input_per_million
            + (output_tokens / TOKENS_PER_PRICE_UNIT) * self.output_per_million
        )


@dataclass
class Reservation:
    call_id: str
    reserved: float
    attempts: int
    settled: bool = False
    confirmed: float | None = None
    reason: str = ""


@dataclass
class BudgetLedger:
    """Reserve-before-dispatch accounting against an approved ceiling.

    Thread-safe: reservations are taken under a lock so two concurrent callers
    cannot both pass a check the remaining budget covers once.
    """
    ceiling_usd: float
    prices: Prices
    max_output_tokens: int
    max_attempts: int = 3          # 1 initial + 2 retries

    _confirmed: float = 0.0
    _reservations: dict[str, Reservation] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ── accounting views ────────────────────────────────────────────────────

    @property
    def confirmed_cost(self) -> float:
        """Spend backed by usage the provider actually reported."""
        return self._confirmed

    @property
    def unknown_exposure(self) -> float:
        """Worst-case cost of calls that never returned usage.

        Held, not released. A timed-out call was probably billed.
        """
        return sum(r.reserved for r in self._reservations.values() if not r.settled)

    @property
    def outstanding_reserved(self) -> float:
        """Reservations for calls still in flight or still unreconciled."""
        return self.unknown_exposure

    @property
    def committed(self) -> float:
        """What the ceiling is enforced against."""
        return self.confirmed_cost + self.unknown_exposure

    @property
    def remaining(self) -> float:
        return self.ceiling_usd - self.committed

    @property
    def unreconciled_calls(self) -> int:
        return sum(1 for r in self._reservations.values() if not r.settled)

    # ── the reserve / settle cycle ──────────────────────────────────────────

    def worst_case(self, input_tokens: int) -> float:
        """Cost if this call uses every permitted attempt and the full output cap."""
        per_attempt = self.prices.cost(input_tokens, self.max_output_tokens)
        return per_attempt * self.max_attempts

    def reserve(self, call_id: str, input_tokens: int) -> Reservation:
        """Reserve worst-case cost BEFORE dispatch. Raises if it would exceed.

        Taken under a lock and recorded immediately, so a second caller sees this
        reservation even though no response has arrived.
        """
        amount = self.worst_case(input_tokens)
        with self._lock:
            if call_id in self._reservations:
                raise ValueError(f"call_id already reserved: {call_id}")
            if self.committed + amount > self.ceiling_usd:
                raise BudgetExceeded(
                    f"reserving {amount:.6f} would exceed ceiling "
                    f"{self.ceiling_usd:.6f} (committed {self.committed:.6f})")
            reservation = Reservation(call_id=call_id, reserved=amount,
                                      attempts=self.max_attempts)
            self._reservations[call_id] = reservation
            return reservation

    def settle(self, call_id: str, *, input_tokens: int, output_tokens: int,
               attempts: int = 1) -> float:
        """Settle with usage the provider reported. Releases the reservation.

        `attempts` is the number actually issued, so a call that succeeded first
        try releases the retry headroom it never used.
        """
        with self._lock:
            reservation = self._reservations.get(call_id)
            if reservation is None:
                raise KeyError(f"no reservation for {call_id}")
            if reservation.settled:
                raise ValueError(f"already settled: {call_id}")
            actual = self.prices.cost(input_tokens, output_tokens) * max(1, attempts)
            reservation.settled = True
            reservation.confirmed = actual
            self._confirmed += actual
            del self._reservations[call_id]
            self._settled_history.append(reservation)
            return actual

    def settle_unknown(self, call_id: str, reason: str = "no usage returned") -> None:
        """Mark a call as billed-but-unmeasured. The reservation is KEPT.

        This is the timeout case. The call may well have been processed and
        charged, so its worst-case cost continues to occupy budget until a human
        reconciles it against the provider's own usage console.
        """
        with self._lock:
            reservation = self._reservations.get(call_id)
            if reservation is None:
                raise KeyError(f"no reservation for {call_id}")
            reservation.reason = reason
            # Deliberately NOT settled and NOT deleted.

    def reconcile(self, call_id: str, *, input_tokens: int,
                  output_tokens: int, attempts: int = 1) -> float:
        """Resolve an unknown call from out-of-band usage data (billing console)."""
        return self.settle(call_id, input_tokens=input_tokens,
                           output_tokens=output_tokens, attempts=attempts)

    def release(self, call_id: str) -> None:
        """Release a reservation for a call that provably never dispatched.

        Only for a failure BEFORE the request left the process -- a validation
        error, a refused file read. Never for a network timeout, where the request
        may have arrived.
        """
        with self._lock:
            self._reservations.pop(call_id, None)

    _settled_history: list[Reservation] = field(default_factory=list, repr=False)

    # ── reporting ───────────────────────────────────────────────────────────

    def as_report_dict(self) -> dict:
        """Two figures, never one. A run with unknown exposure is ESTIMATED."""
        final = self.unreconciled_calls == 0
        return {
            "ceiling_usd": self.ceiling_usd,
            "confirmed_cost": round(self.confirmed_cost, 6),
            "unknown_exposure": round(self.unknown_exposure, 6),
            "committed": round(self.committed, 6),
            "remaining": round(self.remaining, 6),
            "calls_settled": len(self._settled_history),
            "calls_unreconciled": self.unreconciled_calls,
            "status": "FINAL" if final else "ESTIMATED",
            "note": (
                "All calls reconciled." if final else
                "Unreconciled calls hold their reservation. Spend is a worst-case "
                "estimate until checked against the provider's usage console."
            ),
        }

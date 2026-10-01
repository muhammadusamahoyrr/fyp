"""Privacy regression tests for appointment access-denial logging."""

import logging

import pytest

from app.core.exceptions import ForbiddenError
from app.services import appointment_service


@pytest.mark.parametrize(
    ("exists", "reason"),
    [(True, "not_a_party"), (False, "no_such_appointment")],
)
async def test_access_denial_logs_reason_but_not_appointment_id(
    monkeypatch, caplog, exists, reason,
):
    sensitive_appointment_id = f"private-appointment-{reason}"

    async def find_for_actor(appt_id, actor_filter):
        return None

    async def find_by_id(appt_id):
        return {"_id": appt_id} if exists else None

    monkeypatch.setattr(
        appointment_service.appt_repo, "find_for_actor", find_for_actor)
    monkeypatch.setattr(
        appointment_service.appt_repo, "find_by_id", find_by_id)

    with caplog.at_level(
        logging.INFO, logger="app.services.appointment_service"
    ):
        with pytest.raises(ForbiddenError) as denied:
            await appointment_service._load_for_actor(
                sensitive_appointment_id, "actor-id", "client")

    assert denied.value.status_code == 403
    assert denied.value.detail == "Appointment not available"
    assert "appointment_access_denied" in caplog.text
    assert "role=client" in caplog.text
    assert f"reason={reason}" in caplog.text
    assert sensitive_appointment_id not in caplog.text

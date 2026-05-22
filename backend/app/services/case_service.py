import secrets
from datetime import datetime, timezone

from app.core.constants import CaseStatus
from app.core.exceptions import ForbiddenError, NotFoundError
from app.repositories.case_repo import CaseRepository

case_repo = CaseRepository()


def _gen_case_number() -> str:
    return f"ATT-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}"


async def create_case(client_id: str, data: dict) -> dict:
    case_id = secrets.token_urlsafe(16)
    doc = {
        "_id": case_id,
        "case_number": _gen_case_number(),
        "client_id": client_id,
        "lawyer_id": None,
        "intake_id": data.get("intake_id"),
        "case_type": data["case_type"],
        "province": data["province"],
        "status": CaseStatus.OPEN.value,
        "title": data["title"],
        "description": data["description"],
        "milestones": [],
        "hearing_dates": [],
        "case_embedding": None,  # TODO: AI — embed case description at creation
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    await case_repo.insert(doc)
    return doc


async def get_case(case_id: str, requester_id: str, requester_role: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)
    return case


async def list_cases(user_id: str, role: str, page: int, page_size: int):
    if role == "client":
        return await case_repo.find_by_client(user_id, page, page_size)
    if role == "lawyer":
        return await case_repo.find_by_lawyer(user_id, page, page_size)
    return await case_repo.paginate({}, page, page_size)


async def update_case(
    case_id: str, updates: dict, requester_id: str, requester_role: str
) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    _assert_access(case, requester_id, requester_role)

    updates["updated_at"] = datetime.now(timezone.utc)
    await case_repo.update_one({"_id": case_id}, {"$set": updates})
    return await case_repo.find_by_id(case_id)


async def add_milestone(case_id: str, milestone: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can add milestones")

    milestone["completed"] = False
    milestone["completed_at"] = None
    await case_repo.add_milestone(case_id, milestone)
    return await case_repo.find_by_id(case_id)


async def add_hearing(case_id: str, hearing: dict, lawyer_id: str) -> dict:
    case = await case_repo.find_by_id(case_id)
    if not case:
        raise NotFoundError("Case")
    if case.get("lawyer_id") != lawyer_id:
        raise ForbiddenError("Only the assigned lawyer can schedule hearings")

    await case_repo.add_hearing(case_id, hearing)
    return await case_repo.find_by_id(case_id)


def _assert_access(case: dict, user_id: str, role: str) -> None:
    if role == "admin":
        return
    if role == "client" and case.get("client_id") == user_id:
        return
    if role == "lawyer" and case.get("lawyer_id") == user_id:
        return
    raise ForbiddenError("Access denied to this case")

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse


class AuthError(HTTPException):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},  # RFC 7235 requirement
        )


class ForbiddenError(HTTPException):
    def __init__(self, detail: str = "Insufficient permissions"):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class NotFoundError(HTTPException):
    def __init__(self, resource: str = "Resource"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} not found",
        )


class ConflictError(HTTPException):
    def __init__(self, detail: str = "Resource already exists"):
        super().__init__(status_code=status.HTTP_409_CONFLICT, detail=detail)


class AppValidationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


class AIServiceError(HTTPException):
    def __init__(self, detail: str = "AI service unavailable"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail
        )


class ServiceUnavailableError(HTTPException):
    def __init__(self, detail: str = "Service temporarily unavailable"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail
        )


#: Statuses whose reason is worth a log line. 401/403/404 are deliberately
#: absent: they are the routine noise of any authenticated API and would bury
#: the rest. What is here is the class of refusal that means "you sent
#: something the product will not accept, and there is a specific reason" --
#: precisely the thing a caller may be unable to show its user.
_LOGGED_REFUSALS = frozenset({400, 409, 422})


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # RECORDED, not only returned. A refusal used to exist solely in the
    # response body: if the client swallowed it -- or rendered it in a toast at
    # the top of a page the user had scrolled away from -- the server kept only
    # a status code. That is how "Sign & Send does nothing" survived several
    # rounds of investigation while the server was plainly saying, every time,
    # that the agreement still contained the unreviewed-sample notice.
    if exc.status_code in _LOGGED_REFUSALS:
        import logging
        logging.getLogger(__name__).warning(
            "%d on %s %s -- %s", exc.status_code, request.method,
            request.url.path, str(exc.detail)[:300])

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code},
        headers=getattr(exc, "headers", None) or {},
    )


async def validation_exception_handler(request, exc) -> JSONResponse:
    """A 422, with the failing field written to the log.

    FastAPI returns the detail to the caller and records NOTHING server-side. A
    client that swallows the body -- or shows it in a toast at the top of a
    page the user has scrolled away from -- leaves a 422 in the access log with
    no way to tell which field was wrong. That is exactly how a Sign & Send
    that "does nothing" stayed unexplained across several attempts.

    ONLY THE LOCATION AND THE RULE ARE LOGGED, never the value. These payloads
    carry signature images and agreement text: the useful part of a validation
    failure is which field broke which constraint, and the value is both
    enormous and the caller's private content.
    """
    import logging

    errors = exc.errors() if hasattr(exc, "errors") else []
    summary = "; ".join(
        f"{'.'.join(str(p) for p in e.get('loc', ()))}: {e.get('type')}"
        for e in errors
    ) or "unspecified"
    logging.getLogger(__name__).warning(
        "422 on %s %s -- %s", request.method, request.url.path, summary)

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "The request was not valid.",
                 "status_code": 422,
                 "detail": errors},
    )


async def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={"error": "Too many requests. Please slow down.", "status_code": 429},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error", "status_code": 500},
    )


class ReviewLimitError(HTTPException):
    """A document has been reviewed as many times as it can be.

    Its own class rather than a ConflictError with distinguishing prose, because
    the caller's response differs completely. Every other 409 on this surface
    means "reload and try again" and is worth retrying; this one is permanent
    for this document, and retrying is the one thing that cannot help. A client
    that cannot tell them apart retries forever.
    """

    def __init__(self, detail: str = "This document has reached its review limit."):
        super().__init__(status_code=409, detail=detail)

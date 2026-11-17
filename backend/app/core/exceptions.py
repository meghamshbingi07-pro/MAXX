from fastapi import Request
from fastapi.responses import JSONResponse


class MAXXException(Exception):
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code


async def maxx_exception_handler(
    request: Request,
    exc: MAXXException,
):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.message,
            "type": "maxx_error",
        },
    )
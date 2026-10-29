# def error_response(msg: str) -> dict:
#     return {"results": {"message": msg}}


def error_response(msg: str) -> dict:
    return {"detail": msg}

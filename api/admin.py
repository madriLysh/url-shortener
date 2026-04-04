from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_url_service, verify_api_key
from api.schemas import URLDeleteResponse
from services import URLService

router = APIRouter(prefix="/admin", dependencies=[Depends(verify_api_key)])

def _handle_service_error(operation):
    try:
        operation()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

@router.delete("/urls/{short_code}")
def delete_url(
    short_code: str,
    service: URLService = Depends(get_url_service)
    ):
    _handle_service_error(lambda: service.delete_url(short_code))
    return {"detail": "URL deleted successfully"}

@router.post("/urls/{short_code}/restore")
def restore_url(
    short_code: str,
    service: URLService = Depends(get_url_service)
    ):
    _handle_service_error(lambda: service.restore_url(short_code))
    return {"detail": "URL restored successfully"}

@router.post("/urls/cleanup", response_model=URLDeleteResponse)
def cleanup_expired_urls(
    service: URLService = Depends(get_url_service)
    ):
    deleted_count = service.deactivate_expired_urls()
    return {"detail": f"Cleaned up {deleted_count} expired URLs", "deleted_count": deleted_count}

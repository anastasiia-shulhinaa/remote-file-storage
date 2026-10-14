from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_sync_service
from app.core.security import CurrentUser, get_current_user
from app.schemas.sync import (
    FinishRollbackRequest,
    SynchronizationDetails,
    SynchronizationDto,
    SynchronizationPlan,
    SynchronizationUpdate,
    SyncRequest,
)
from app.services.synchronization_service import SynchronizationService

router = APIRouter(tags=["synchronization"])


@router.post("/sync", response_model=SynchronizationPlan)
def synchronize(
    request: SyncRequest,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """SynchronizationController: local manifest in, synchronization plan out.

    No file content is sent here — the client (desktop or web) executes the plan
    through POST /files, GET /files/{id}/content and DELETE /files/{id} (passing
    synchronization_id, so remote changes are journaled and can be rolled back),
    then reports the result with PATCH /synchronizations/{synchronization_id}.
    409 sync_in_progress: another sync or rollback is active for this folder.
    """
    return sync.run(user.id, request.remote_folder_id, request.manifest, request.mode, request.client,
                    request.device)


@router.get("/synchronizations", response_model=list[SynchronizationDto])
def list_synchronizations(
    limit: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """Synchronization history of the current user, newest first."""
    return sync.list_history(user.id, limit)


@router.get("/synchronizations/{synchronization_id}", response_model=SynchronizationDetails)
def get_synchronization(
    synchronization_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """Session state + journaled remote operations (used to resume after a reconnect)."""
    return sync.details(user.id, synchronization_id)


@router.post("/sync/{synchronization_id}/cancel", response_model=SynchronizationDto)
def cancel_synchronization(
    synchronization_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """RUNNING → CANCEL_REQUESTED. Idempotent. From now on no journaled change is accepted."""
    return sync.cancel(user.id, synchronization_id)


@router.post("/sync/{synchronization_id}/rollback", response_model=SynchronizationDetails)
def rollback_synchronization(
    synchronization_id: UUID,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """CANCEL_REQUESTED → ROLLING_BACK and reverse the remote changes (each at most once).

    Call it after the client has stopped executing; it may be called again to resume.
    """
    return sync.rollback(user.id, synchronization_id)


@router.post("/sync/{synchronization_id}/rollback/finish", response_model=SynchronizationDetails)
def finish_rollback(
    synchronization_id: UUID,
    request: FinishRollbackRequest,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """The client reports its local rollback → CANCELLED or ROLLBACK_FAILED."""
    return sync.finish_rollback(user.id, synchronization_id, request)


@router.patch("/synchronizations/{synchronization_id}", response_model=SynchronizationDto)
def report_synchronization(
    synchronization_id: UUID,
    request: SynchronizationUpdate,
    user: CurrentUser = Depends(get_current_user),
    sync: SynchronizationService = Depends(get_sync_service),
):
    """Progress / result of an executed plan: PENDING → RUNNING → COMPLETED | FAILED.

    409 sync_cancelled when the session was cancelled meanwhile: the client must stop.
    """
    return sync.report(user.id, synchronization_id, request)

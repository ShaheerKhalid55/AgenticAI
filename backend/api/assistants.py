from fastapi import APIRouter, Depends, HTTPException

from ..auth.security import get_current_user, require_role
from ..models.api_models import (
    AssistantConfiguration,
    AssistantConfigurationUpdate,
    AssistantToolStatus,
)

router = APIRouter(prefix="/api/assistants", tags=["assistants"])


@router.get("/current", response_model=AssistantConfiguration)
def current_assistant(current_user: dict = Depends(get_current_user)):
    from ..main import services
    return services.mongo.get_assistant(current_user["tenant_id"])


@router.patch("/{assistant_id}", response_model=AssistantConfiguration)
def update_assistant(
    assistant_id: str,
    request: AssistantConfigurationUpdate,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services
    updates = request.model_dump(exclude_unset=True)
    if "enabled_tools" in updates:
        current = services.mongo.get_assistant(current_user["tenant_id"], assistant_id)
        catalog = services.agent.tool_catalog({**current, "enabled_tools": updates["enabled_tools"]})
        known = {tool["id"] for tool in catalog}
        unknown = sorted(set(updates["enabled_tools"]) - known)
        unavailable = sorted(tool["id"] for tool in catalog if tool["enabled"] and not tool["available"])
        if unknown:
            raise HTTPException(422, f"Unknown tools: {', '.join(unknown)}")
        if unavailable:
            raise HTTPException(422, f"Unavailable tools cannot be enabled: {', '.join(unavailable)}")
    return services.mongo.update_assistant(current_user["tenant_id"], assistant_id, updates)


@router.get("/{assistant_id}/tools", response_model=list[AssistantToolStatus])
def assistant_tools(
    assistant_id: str,
    current_user: dict = Depends(require_role("company_admin")),
):
    from ..main import services
    assistant = services.mongo.get_assistant(current_user["tenant_id"], assistant_id)
    return services.agent.tool_catalog(assistant)

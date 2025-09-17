# /shared/request_context.py
from typing import Optional
from .logging_config import (
    cv_process_id, cv_run_id, cv_triggered_by, cv_endpoint, cv_function
)

def set_request_context(
    *,
    process_id: Optional[str] = None,
    run_id: Optional[str] = None,
    triggered_by: Optional[str] = None,
    endpoint: Optional[str] = None,
    function_name: Optional[str] = None,
):
    """Call once at the start of each request/trigger."""
    if process_id is not None:   cv_process_id.set(process_id)
    if run_id is not None:       cv_run_id.set(run_id)
    if triggered_by is not None: cv_triggered_by.set(triggered_by)
    if endpoint is not None:     cv_endpoint.set(endpoint)
    if function_name is not None:cv_function.set(function_name)

def clear_request_context():
    """Optional: call at end if you run background tasks or reuse workers."""
    for cv in (cv_process_id, cv_run_id, cv_triggered_by, cv_endpoint, cv_function):
        cv.set(None)

"""
Gating dependency for DataPilot backend.
Returns 409 "No dataset" when the authenticated user has not uploaded any datasets yet.
"""
from fastapi import Depends, HTTPException
from .auth import current_user
from .db import datasets


def require_dataset(user=Depends(current_user)):
    """
    Enforces that the user has at least one active dataset.
    Returns 409 Conflict if no datasets exist for the user.
    """
    count = datasets.count_documents({"owner": user["_id"]})
    if count == 0:
        raise HTTPException(
            status_code=409,
            detail="No dataset available. Please upload an Excel or CSV file to get started.",
        )
    return user

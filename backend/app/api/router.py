from fastapi import APIRouter, Depends

from app.api.deps import require_recruiter
from app.api.v1.assessments import router as assessments_router
from app.api.v1.auth import router as auth_router
from app.api.v1.careers import router as careers_router
from app.api.v1.claims import router as claims_router
from app.api.v1.copilot import router as copilot_router
from app.api.v1.health import router as health_router
from app.api.v1.interview_reports import router as interview_reports_router
from app.api.v1.interview_sessions import router as interview_sessions_router
from app.api.v1.invites import router as invites_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.notices import router as notices_router
from app.api.v1.policies import router as policies_router
from app.api.v1.progress import router as progress_router
from app.api.v1.quizzes import router as quizzes_router
from app.api.v1.screening import router as screening_router

_recruiter = [Depends(require_recruiter)]

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(policies_router, tags=["policies"], dependencies=_recruiter)
api_router.include_router(jobs_router, tags=["jobs"], dependencies=_recruiter)
api_router.include_router(careers_router, tags=["careers"], dependencies=_recruiter)
api_router.include_router(copilot_router, tags=["copilot"], dependencies=_recruiter)
api_router.include_router(screening_router, tags=["screening"], dependencies=_recruiter)
api_router.include_router(progress_router, tags=["progress"], dependencies=_recruiter)
api_router.include_router(notices_router, tags=["notifications"], dependencies=_recruiter)
api_router.include_router(assessments_router, tags=["assessments"], dependencies=_recruiter)
api_router.include_router(claims_router, tags=["claims"], dependencies=_recruiter)
api_router.include_router(interview_reports_router, tags=["interview-reports"], dependencies=_recruiter)
api_router.include_router(invites_router, tags=["invites"])
api_router.include_router(interview_sessions_router, tags=["interviews"])
api_router.include_router(quizzes_router, tags=["quizzes"])

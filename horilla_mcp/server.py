"""
MCP tools for the recruitment pipeline and employees.

Plain ORM calls, so model logic (Candidate.save() etc.) still runs. Every tool
returns plain dicts/lists; failures come back as {"error": "..."}.
"""

import functools
from datetime import date

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import Count, Q
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from base.models import JobPosition
from employee.models import Employee, EmployeeNote
from recruitment.methods import convert_candidate_to_employee
from recruitment.models import (
    Candidate,
    Recruitment,
    RejectedCandidate,
    RejectReason,
    SkillZone,
    SkillZoneCandidate,
    Stage,
    StageNote,
)

# The server sits behind Caddy on its own hostname and every request needs the
# token, so the localhost-only Host check (DNS rebinding) is turned off.
mcp = FastMCP(
    "horilla",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

PAGE_SIZE = 50
CANDIDATE_FIELDS = [
    "name",
    "email",
    "mobile",
    "portfolio",
    "address",
    "gender",
    "dob",
    "joining_date",
]
EMPLOYEE_FIELDS = [
    "employee_first_name",
    "employee_last_name",
    "phone",
    "email",
    "address",
    "dob",
    "gender",
]
WORK_INFO_FIELDS = [
    "date_joining",
    "contract_end_date",
    "job_position_id",
    "department_id",
    "employee_type_id",
    "location",
    "basic_salary",
]


def tool(fn):
    """Register fn as an MCP tool, turning expected failures into error dicts."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        close_old_connections()
        try:
            return fn(*args, **kwargs)
        except ObjectDoesNotExist as e:
            return {"error": f"Not found: {e}"}
        except ValidationError as e:
            return {"error": "; ".join(e.messages)}
        except IntegrityError as e:
            return {"error": f"Database constraint failed: {e}"}

    return mcp.tool()(wrapper)


def _page(qs, page):
    start = (max(page, 1) - 1) * PAGE_SIZE
    meta = {"total": qs.count(), "page": page, "page_size": PAGE_SIZE}
    return meta, qs[start : start + PAGE_SIZE]


def _update(obj, fields, allowed):
    """Set allow-listed fields, validate only those, save."""
    bad = [k for k in fields if k not in allowed]
    if bad:
        return {"error": f"Fields not allowed: {bad}. Allowed: {allowed}"}
    for name, value in fields.items():
        setattr(obj, obj._meta.get_field(name).attname, value)
    obj.clean_fields(exclude=[f.name for f in obj._meta.fields if f.name not in fields])
    obj.save()
    return {"updated": list(fields)}


def _candidate(c):
    return {
        "id": c.pk,
        "name": c.name,
        "email": c.email,
        "mobile": c.mobile,
        "recruitment_id": c.recruitment_id_id,
        "stage_id": c.stage_id_id,
        "stage": c.stage_id.stage if c.stage_id else None,
        "hired": c.hired,
        "canceled": c.canceled,
        "converted_employee_id": c.converted_employee_id_id,
        "joining_date": c.joining_date,
    }


def _employee(e):
    wi = getattr(e, "employee_work_info", None)
    return {
        "id": e.pk,
        "badge_id": e.badge_id,
        "name": e.get_full_name(),
        "email": e.email,
        "phone": e.phone,
        "is_active": e.is_active,
        "job_position": str(wi.job_position_id) if wi and wi.job_position_id else None,
        "department": str(wi.department_id) if wi and wi.department_id else None,
        "date_joining": wi.date_joining if wi else None,
    }


# --- recruitment lookups -----------------------------------------------------


@tool
def list_recruitments(open_only: bool = True):
    """List recruitments with their stages (id, name, type, candidate count)."""
    qs = Recruitment.objects.all()
    if open_only:
        qs = qs.filter(closed=False)
    return [
        {
            "id": r.pk,
            "title": r.title,
            "closed": r.closed,
            "is_event_based": r.is_event_based,
            "job_position_id": r.job_position_id_id,
            "stages": [
                {
                    "id": s.pk,
                    "name": s.stage,
                    "stage_type": s.stage_type,
                    "sequence": s.sequence,
                    "candidates": s.n,
                }
                for s in Stage.objects.filter(recruitment_id=r)
                .annotate(n=Count("candidate"))
                .order_by("sequence")
            ],
        }
        for r in qs
    ]


@tool
def list_job_positions():
    """List job positions (id, name, department)."""
    return [
        {"id": j.pk, "name": j.job_position, "department": str(j.department_id)}
        for j in JobPosition.objects.all()
    ]


# --- candidates --------------------------------------------------------------


@tool
def list_candidates(
    recruitment_id: int | None = None,
    stage_id: int | None = None,
    search: str | None = None,
    status: str | None = None,
    page: int = 1,
):
    """List candidates, 50 per page. status: active, rejected, hired or converted.
    search matches name, email or mobile."""
    qs = Candidate.objects.all().order_by("-pk")
    if recruitment_id:
        qs = qs.filter(recruitment_id=recruitment_id)
    if stage_id:
        qs = qs.filter(stage_id=stage_id)
    if search:
        qs = qs.filter(
            Q(name__icontains=search)
            | Q(email__icontains=search)
            | Q(mobile__icontains=search)
        )
    if status == "rejected":
        qs = qs.filter(rejected_candidate__isnull=False)
    elif status == "hired":
        qs = qs.filter(hired=True)
    elif status == "converted":
        qs = qs.filter(converted_employee_id__isnull=False)
    elif status == "active":
        qs = qs.filter(
            rejected_candidate__isnull=True,
            hired=False,
            converted_employee_id__isnull=True,
        )
    elif status:
        return {"error": "status must be active, rejected, hired or converted"}
    meta, rows = _page(qs.select_related("stage_id"), page)
    return {**meta, "results": [_candidate(c) for c in rows]}


@tool
def get_candidate(candidate_id: int):
    """Candidate details with notes, talent pools and rejection."""
    c = Candidate.objects.get(pk=candidate_id)
    rejected = RejectedCandidate.objects.filter(candidate_id=c).first()
    return {
        **_candidate(c),
        "portfolio": c.portfolio,
        "address": c.address,
        "gender": c.gender,
        "dob": c.dob,
        "notes": [
            {"id": n.pk, "stage_id": n.stage_id_id, "text": n.description}
            for n in StageNote.objects.filter(candidate_id=c).order_by("pk")
        ],
        "talent_pools": [
            {
                "pool_id": z.skill_zone_id_id,
                "pool": str(z.skill_zone_id),
                "reason": z.reason,
            }
            for z in SkillZoneCandidate.objects.filter(candidate_id=c)
        ],
        "rejection": rejected
        and {
            "reasons": list(rejected.reject_reason_id.values_list("title", flat=True)),
            "description": rejected.description,
        },
    }


@tool
def add_candidates(
    recruitment_id: int,
    candidates: list[dict],
    stage_id: int | None = None,
    job_position_id: int | None = None,
):
    """Bulk-create candidates in a recruitment (default stage: its first).
    Each item: name, email (required), mobile, portfolio, address, gender
    (male/female/other), dob (YYYY-MM-DD), note (free text, stored as a stage
    note). job_position_id is only needed for event-based recruitments.
    Duplicates (email + recruitment) and invalid rows are skipped and reported."""
    recruitment = Recruitment.objects.get(pk=recruitment_id)
    stages = Stage.objects.filter(recruitment_id=recruitment)
    stage = stages.get(pk=stage_id) if stage_id else stages.order_by("sequence").first()
    if stage is None:
        return {"error": "Recruitment has no stages"}
    created, skipped = [], []
    for i, row in enumerate(candidates):
        email = (row.get("email") or "").strip()
        if not email:
            skipped.append({"row": i, "name": row.get("name"), "reason": "no email"})
            continue
        if Candidate.objects.filter(
            recruitment_id=recruitment, email__iexact=email
        ).exists():
            skipped.append({"row": i, "email": email, "reason": "duplicate"})
            continue
        try:
            with transaction.atomic():
                c = Candidate(
                    recruitment_id=recruitment,
                    stage_id=stage,
                    job_position_id_id=job_position_id,
                    source="other",
                    email=email,
                    **{
                        k: row[k]
                        for k in ("name", "mobile", "portfolio", "address", "gender", "dob")
                        if row.get(k)
                    },
                )
                c.full_clean(exclude=["resume", "profile"])
                c.save()
                if row.get("note"):
                    StageNote.objects.create(
                        candidate_id=c, stage_id=stage, description=row["note"]
                    )
            created.append({"id": c.pk, "email": email})
        except (ValidationError, IntegrityError) as e:
            reason = "; ".join(e.messages) if isinstance(e, ValidationError) else str(e)
            skipped.append({"row": i, "email": email, "reason": reason})
    return {"created": created, "skipped": skipped}


@tool
def update_candidate(candidate_id: int, fields: dict):
    """Update candidate fields. Allowed: name, email, mobile, portfolio, address,
    gender, dob, joining_date."""
    return _update(Candidate.objects.get(pk=candidate_id), fields, CANDIDATE_FIELDS)


@tool
def move_candidate(candidate_id: int, stage_id: int):
    """Move a candidate to another stage of the same recruitment."""
    c = Candidate.objects.get(pk=candidate_id)
    stage = Stage.objects.get(pk=stage_id, recruitment_id=c.recruitment_id)
    c.stage_id = stage
    # Candidate.save() forces a canceled candidate back to the cancelled stage
    c.canceled = stage.stage_type == "cancelled"
    c.save()
    return _candidate(c)


@tool
def add_candidate_note(candidate_id: int, text: str):
    """Add a note to the candidate's current stage."""
    c = Candidate.objects.get(pk=candidate_id)
    n = StageNote.objects.create(candidate_id=c, stage_id=c.stage_id, description=text)
    return {"note_id": n.pk}


# --- rejection ---------------------------------------------------------------


@tool
def list_reject_reasons():
    """List reject reasons."""
    return [
        {"id": r.pk, "title": r.title, "description": r.description}
        for r in RejectReason.objects.all()
    ]


@tool
def create_reject_reason(title: str, description: str = ""):
    """Create a reject reason."""
    r = RejectReason(title=title, description=description)
    r.full_clean(exclude=["company_id"])
    r.save()
    return {"id": r.pk}


@tool
def reject_candidate(
    candidate_id: int,
    reason_ids: list[int],
    description: str,
    move_to_cancelled: bool = True,
):
    """Reject a candidate with reasons; moves them to the cancelled stage if the
    recruitment has one."""
    c = Candidate.objects.get(pk=candidate_id)
    reasons = list(RejectReason.objects.filter(pk__in=reason_ids))
    if len(reasons) != len(set(reason_ids)):
        return {"error": "Unknown reason id"}
    with transaction.atomic():
        rejected, _ = RejectedCandidate.objects.update_or_create(
            candidate_id=c, defaults={"description": description}
        )
        rejected.reject_reason_id.set(reasons)
        cancelled = Stage.objects.filter(
            recruitment_id=c.recruitment_id, stage_type="cancelled"
        ).first()
        if move_to_cancelled and cancelled:
            c.stage_id = cancelled
            c.save()
    return _candidate(c)


# --- talent pools ------------------------------------------------------------


@tool
def list_talent_pools():
    """List talent pools."""
    return [
        {"id": z.pk, "title": z.title, "description": z.description}
        for z in SkillZone.objects.all()
    ]


@tool
def create_talent_pool(title: str, description: str = ""):
    """Create a talent pool."""
    z = SkillZone(title=title, description=description)
    z.full_clean(exclude=["company_id"])
    z.save()
    return {"id": z.pk}


@tool
def add_to_talent_pool(candidate_id: int, pool_id: int, reason: str):
    """Add a candidate to a talent pool."""
    z = SkillZoneCandidate(
        candidate_id=Candidate.objects.get(pk=candidate_id),
        skill_zone_id=SkillZone.objects.get(pk=pool_id),
        reason=reason,
    )
    z.full_clean()
    z.save()
    return {"id": z.pk}


@tool
def remove_from_talent_pool(candidate_id: int, pool_id: int):
    """Remove a candidate from a talent pool."""
    n, _ = SkillZoneCandidate.objects.filter(
        candidate_id=candidate_id, skill_zone_id=pool_id
    ).delete()
    return {"removed": n}


# --- hiring ------------------------------------------------------------------


@tool
def hire_candidate(
    candidate_id: int, joining_date: date | None = None, convert: bool = True
):
    """Move a candidate to the recruitment's hired stage, set the joining date
    and (convert=True) create the employee, with date_joining set."""
    c = Candidate.objects.get(pk=candidate_id)
    stage = (
        Stage.objects.filter(recruitment_id=c.recruitment_id, stage_type="hired")
        .order_by("sequence")
        .first()
    )
    if stage is None:
        return {"error": "Recruitment has no hired stage"}
    with transaction.atomic():
        c.stage_id = stage
        c.canceled = False
        if joining_date:
            c.joining_date = joining_date
        c.save()
        result = {"candidate": _candidate(c)}
        if convert:
            if c.converted_employee_id:
                result["employee_id"] = c.converted_employee_id_id
                result["message"] = "Already converted"
                return result
            employee, message = convert_candidate_to_employee(c)
            result["message"] = str(message)
            if employee:
                result["employee_id"] = employee.pk
                if joining_date:
                    wi = employee.employee_work_info
                    wi.date_joining = joining_date
                    wi.save()
    return result


# --- employees ---------------------------------------------------------------


@tool
def list_employees(search: str | None = None, active: bool = True, page: int = 1):
    """List employees, 50 per page. search matches name, email or badge id."""
    qs = Employee.objects.filter(is_active=active).order_by("pk")
    if search:
        qs = qs.filter(
            Q(employee_first_name__icontains=search)
            | Q(employee_last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(badge_id__icontains=search)
        )
    meta, rows = _page(qs.select_related("employee_work_info"), page)
    return {**meta, "results": [_employee(e) for e in rows]}


@tool
def get_employee(employee_id: int):
    """Employee details with work information."""
    e = Employee.objects.get(pk=employee_id)
    wi = getattr(e, "employee_work_info", None)
    return {
        **_employee(e),
        "address": e.address,
        "dob": e.dob,
        "gender": e.gender,
        "job_role": str(wi.job_role_id) if wi and wi.job_role_id else None,
        "shift": str(wi.shift_id) if wi and wi.shift_id else None,
        "employee_type": (
            str(wi.employee_type_id) if wi and wi.employee_type_id else None
        ),
        "location": wi.location if wi else None,
        "contract_end_date": wi.contract_end_date if wi else None,
    }


@tool
def update_employee(employee_id: int, fields: dict):
    """Update employee fields. Allowed: employee_first_name, employee_last_name,
    phone, email, address, dob, gender."""
    return _update(Employee.objects.get(pk=employee_id), fields, EMPLOYEE_FIELDS)


@tool
def update_work_info(employee_id: int, fields: dict):
    """Update work information. Allowed: date_joining, contract_end_date,
    job_position_id, department_id, employee_type_id, location, basic_salary."""
    wi = Employee.objects.get(pk=employee_id).employee_work_info
    return _update(wi, fields, WORK_INFO_FIELDS)


@tool
def add_employee_note(employee_id: int, text: str):
    """Add a note to an employee."""
    e = Employee.objects.get(pk=employee_id)
    # updated_by is required; there is no logged-in user here, so use the employee
    n = EmployeeNote.objects.create(employee_id=e, description=text, updated_by=e)
    return {"note_id": n.pk}


@tool
def set_employee_active(employee_id: int, active: bool):
    """Archive (active=False) or unarchive an employee."""
    e = Employee.objects.get(pk=employee_id)
    e.is_active = active
    e.save()
    return {"id": e.pk, "is_active": e.is_active}

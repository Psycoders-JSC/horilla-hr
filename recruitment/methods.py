"""
methods.py

This page is used to write reusable methods.

"""

from django.db import IntegrityError
from django.utils.translation import gettext_lazy as _

from recruitment.models import Recruitment, RecruitmentSurvey


def is_stagemanager(request):
    """
    This method is used to check stage manager, if the employee is also
    recruitment manager it returns true
    """
    try:
        employee = request.user.employee_get
        return employee.recruitment_set.exists() or employee.stage_set.exists()
    except Exception:
        return False


def is_recruitmentmanager(request):
    """
    This method is used to check the employee is recruitment manager or not
    """
    try:
        employee = request.user.employee_get
        return employee.recruitment_set.exists()
    except Exception:
        return False


def stage_manages(request, stage):
    """
    This method is used to check the employee manager to this stage."""
    try:
        employee = request.user.employee_get

        return (
            stage.stage_manager.filter(id=employee.id).exists()
            or stage.recruitment_id.recruitment_managers.filter(id=employee.id).exists()
        )
    except Exception:
        return False


def recruitment_manages(request, recruitment):
    """
    This method is used to check the employee is manager to the current recruitment
    """
    try:
        employee = request.user.employee_get
        return recruitment.recruitment_managers.filter(id=employee.id).exists()
    except Exception:
        return False


def update_rec_template_grp(upt_template_ids, template_groups, rec_id):
    recruitment_obj = Recruitment.objects.get(id=rec_id)
    if list(upt_template_ids) != list(template_groups):
        recruitment_surveys = RecruitmentSurvey.objects.filter(recruitment_ids=rec_id)
        if recruitment_surveys:
            for survey in recruitment_surveys:
                survey.recruitment_ids.remove(rec_id)
                survey.save()
        if upt_template_ids:
            rec_surveys_templates = RecruitmentSurvey.objects.filter(
                template_id__in=upt_template_ids
            )
            for survey in rec_surveys_templates:
                survey.recruitment_ids.add(recruitment_obj)


def in_all_managers(request):
    """
    Check the user in any recruitment/onboarding related managers
    """
    return (
        request.user.employee_get.stage_set.exists()
        or request.user.employee_get.recruitment_set.exists()
        or request.user.employee_get.onboardingstage_set.exists()
        or request.user.employee_get.onboarding_task.exists()
    )


def convert_candidate_to_employee(candidate):
    """
    Create an employee from a candidate.
    Returns (employee or None, message); None means nothing was created.
    """
    # local imports: employee/horilla_auth/horilla_documents import recruitment
    from employee.models import Employee
    from horilla_auth.models import HorillaUser
    from horilla_documents.models import Document

    if HorillaUser.objects.filter(username=candidate.email).exists():
        return None, _("User instance with this mail already exists")
    if Employee.objects.filter(employee_user_id__username=candidate.email).exists():
        return None, _("An employee with this email already exists")
    try:
        new_employee = Employee(
            employee_first_name=candidate.name,
            email=candidate.email,
            phone=candidate.mobile,
            gender=candidate.gender,
            is_directly_converted=True,
        )
        new_employee.save()

        work_info = new_employee.employee_work_info
        work_info.job_position_id = candidate.job_position_id
        if candidate.job_position_id:
            work_info.department_id = candidate.job_position_id.department_id
        work_info.company_id = candidate.recruitment_id.company_id
        work_info.save()

        Document.objects.bulk_create(
            [
                Document(
                    title=doc.title,
                    employee_id=new_employee,
                    document=doc.document,
                    status=doc.status,
                    reject_reason=doc.reject_reason,
                )
                for doc in candidate.candidatedocument_set.all()
            ]
        )

        candidate.converted_employee_id = new_employee
        candidate.save()
    except IntegrityError:
        return None, _("An error occurred while creating employee data.")
    return new_employee, _("Candidate has been successfully converted into an employee.")

"""Staff Activity blueprint - monitor team SS member activities"""

from flask import Blueprint, render_template, redirect, url_for, flash, abort
from utils.decorators import staff_required
import backend_auth
from backend_auth import BackendAuthError
import crawler_client as db_data
from crawler_client import CrawlerAPIError
from constants import CONTACT_STATUSES
from helpers import _auth_tokens_from_session

staff_activity_bp = Blueprint("staff_activity", __name__)


@staff_activity_bp.route("/staff-activity")
@staff_required
def index():
    """List all staff members with activity summary"""
    access_token, _ = _auth_tokens_from_session()
    try:
        all_users = backend_auth.list_users(access_token)
    except BackendAuthError as exc:
        flash(str(exc), "error")
        all_users = []
    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    return render_template("staff_activity.html", staff_members=staff_members)


@staff_activity_bp.route("/staff-activity/<string:ss_user_id>")
@staff_required
def detail(ss_user_id):
    """Detail view of one staff member's activities"""
    access_token, _ = _auth_tokens_from_session()

    staff_member = None
    all_users = []
    try:
        all_users = backend_auth.list_users(access_token)
        staff_member = next(
            (u for u in all_users if u["ss_user_id"] == ss_user_id and u.get("role") in ("ss_team", "admin")),
            None,
        )
    except BackendAuthError as exc:
        flash(str(exc), "error")
    if staff_member is None:
        abort(404)

    staff_members = [u for u in all_users if u.get("role") in ("ss_team", "admin")]
    staff_by_id = {u["ss_user_id"]: u for u in all_users}

    try:
        jobs_created = db_data.list_all_jobs(created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        jobs_created = []

    try:
        companies_created = db_data.list_all_companies(created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        companies_created = []

    try:
        contacts_created = db_data.list_all_contacts(access_token, created_by=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_created = []

    try:
        contacts_assigned = db_data.list_all_contacts(access_token, assigned_ss_user=ss_user_id)
    except CrawlerAPIError as exc:
        flash(str(exc), "error")
        contacts_assigned = []

    return render_template(
        "staff_activity_detail.html", staff_member=staff_member,
        staff_members=staff_members, staff_by_id=staff_by_id,
        jobs_created=jobs_created, companies_created=companies_created,
        contacts_created=contacts_created, contacts_assigned=contacts_assigned,
        statuses=CONTACT_STATUSES,
    )

"""HTML pages: public landing, workspace, welcome tour, profile."""
from flask import Blueprint, g, redirect, render_template, url_for

from .auth import load_current_user, login_required_page

bp = Blueprint("pages", __name__)


@bp.get("/")
def landing():
    """Public main page. Logged-in users see a shortcut to their workspace."""
    return render_template("landing.html", user=load_current_user())


@bp.get("/app")
@login_required_page
def workspace():
    if g.user.onboarded_at is None:  # first visit after confirming the email
        return redirect(url_for("pages.welcome"))
    return render_template("index.html", user=g.user, active="documents")


@bp.get("/welcome")
@login_required_page
def welcome():
    return render_template("welcome.html", user=g.user)


@bp.get("/profile")
@login_required_page
def profile():
    return render_template("profile.html", user=g.user, active="profile")

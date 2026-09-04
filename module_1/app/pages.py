"""
app/pages.py
Blueprint containing the routes (sub-pages) for the website:
    /          -> Home page (name, position, bio, picture)
    /contact   -> Contact page (email, LinkedIn)
    /projects  -> Projects page (Module 1 project details + GitHub link)
"""

from flask import Blueprint, render_template

# All page routes are grouped under this blueprint.
pages_bp = Blueprint("pages", __name__)

# ----------------------------------------------------------------------
# Personal information used by the templates.
# Keeping it here means the HTML files only handle layout, not content.
# ----------------------------------------------------------------------
PROFILE = {
    "name": "Godwin Emefiele",
    "position": "Air Dominance Systems Engineer, The Boeing Company",
    "bio": (
        "I am a Systems Engineer at The Boeing Company working on the T-7A "
        "program within Systems Engineering Integration & Test (SEIT). My work "
        "focuses on safety-critical analysis, Safety Critical Function Thread "
        "Analyses (SCFTA), airworthiness gap resolution, and engagement with "
        "government stakeholders across the F-15 and T-7A platforms."
    ),
    "bio_2": (
        "I graduated from the USC Viterbi School of Engineering in 2025 with a "
        "B.S. in Electrical and Computer Engineering (Computer Engineering "
        "emphasis), and I am currently pursuing an M.S. in Artificial "
        "Intelligence at the Johns Hopkins University Whiting School of "
        "Engineering."
    ),
    "email": "pgemefiele@gmail.com",
    "linkedin": "https://www.linkedin.com/in/pammichukwu-emefiele-jr",
    "github": "https://github.com/donpams",
}

# List of projects shown on the Projects page.
# New modules can be added to this list later in the course.
PROJECTS = [
    {
        "title": "Module 1: Personal Flask Website",
        "description": (
            "A personal developer website built with Python and Flask. The site "
            "uses a Flask blueprint to organize its pages, Jinja2 HTML templates "
            "for the layout, and a CSS style sheet for colors and spacing. It "
            "includes a home page with a bio and photo, a contact page, and this "
            "projects page, all connected by a highlighted navigation bar. The "
            "site runs locally on port 8080 with the command 'python run.py'."
        ),
        "link": "https://github.com/donpams/jhu_software_concepts/tree/main/module_1",
    },
]


@pages_bp.route("/")
def home():
    """Render the home page."""
    return render_template("home.html", profile=PROFILE, active_page="home")


@pages_bp.route("/contact")
def contact():
    """Render the contact page."""
    return render_template("contact.html", profile=PROFILE, active_page="contact")


@pages_bp.route("/projects")
def projects():
    """Render the projects page."""
    return render_template(
        "projects.html", profile=PROFILE, projects=PROJECTS, active_page="projects"
    )

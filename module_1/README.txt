Module 1 - Personal Flask Website
Author: Godwin Emefiele
Course: JHU EN.605.256 Modern Software Concepts in Python

DESCRIPTION
-----------
A personal developer website built with Flask. It has three pages
(Home, Contact, Projects) connected by a navigation bar in the top
right corner that highlights the current tab.

FOLDER STRUCTURE
----------------
module_1/
    run.py                  - starts the web server (python run.py)
    requirements.txt        - Python packages needed to run the site
    README.txt              - this file
    screenshots.pdf         - screenshots of each page of the running site
    app/
        __init__.py         - creates the Flask app and registers the blueprint
        pages.py            - blueprint with the routes for each page
        templates/          - HTML templates (base, home, contact, projects)
        static/
            style.css       - CSS styling for the site
            images/         - profile picture

REQUIREMENTS
------------
Python 3.10 or newer.

HOW TO RUN
----------
1. Open a terminal and change into the module_1 folder:
       cd module_1

2. (Recommended) Create and activate a virtual environment:
       python -m venv venv
       source venv/bin/activate        (Mac/Linux)
       venv\Scripts\activate           (Windows)

3. Install the required packages:
       pip install -r requirements.txt

4. Start the site:
       python run.py

5. Open a web browser and go to:
       http://localhost:8080

   Pages:
       http://localhost:8080/           Home
       http://localhost:8080/contact    Contact
       http://localhost:8080/projects   Projects

6. Press CTRL+C in the terminal to stop the server.

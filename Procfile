# Must match render.yaml's startCommand. A bare `gunicorn app:app` takes
# gunicorn's defaults — ONE thread and a THIRTY SECOND timeout — and this app
# streams generations that sit quiet for minutes while a model thinks, on a
# single worker whose threads are also what serve the extension's captures. So
# the default would kill long generations and let one slow request block every
# capture, and it would do it only in whichever environment happened to read
# this file rather than the blueprint.
web: gunicorn app:app --workers 1 --threads 12 --timeout 300

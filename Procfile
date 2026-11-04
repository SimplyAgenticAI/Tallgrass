# Must match render.yaml's startCommand, which is the live service:
# one worker, four threads, 120s timeout. A bare `gunicorn app:app` is
# gunicorn's default — one thread and a thirty second timeout — and that
# would only be what ran in whichever environment read this file instead
# of the blueprint. Do not raise --workers. SQLite on the attached disk
# has one writer process.
web: gunicorn app:app --workers 1 --threads 4 --timeout 120

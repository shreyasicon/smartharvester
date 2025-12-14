#!/bin/bash
set -e

cd myproject   # Or your project directory

# Activate virtualenv if needed
source /myproject/.venv/bin/activate

# Run Django migrations and collect static files
python manage.py migrate --noinput 
python manage.py collectstatic --noinput

echo "Post-script completed successfully." 
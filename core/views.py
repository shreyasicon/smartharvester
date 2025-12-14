# core/views.py
from django.http import JsonResponse
import socket
import os

def health(request):
    """
    Lightweight health check for Elastic Beanstalk and local development.
    Returns HTTP 200 with basic status and hostname.
    """
    return JsonResponse({
        "status": "ok",
        "hostname": socket.gethostname(),
        "debug": os.environ.get("DEBUG", "False")
    })
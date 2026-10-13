"""
Dreema Application Entry Routes
This file defines the root routing table for the application.
"""

from controllers.scanController import ScanController
from dreema.routing import route

# defining all routes coming from the controllers
routes = [
    # creating single routes
    route.post("/api/attendance", ScanController.scan),
]

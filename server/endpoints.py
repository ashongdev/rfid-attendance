"""
Dreema Application Entry Routes
This file defines the root routing table for the application.
"""

import controllers.scanController as Scan
from controllers.adminController import AdminController
from controllers.authController import AuthController
from controllers.scanController import ScanController
from dreema.routing import route

# defining all routes coming from the controllers
routes = [
    # creating single routes
    route.post("/api/attendance", ScanController.scan),
    route(path="/api/attendance", methods=["POST"], handler=Scan.ScanController.scan),
    route(
        path="/api/people/create",
        methods=["POST"],
        handler=AdminController.createPerson,
    ),
    route(path="/api/people", methods=["GET"], handler=AdminController.listPeople),
    route(path="/api/devices", methods=["GET"], handler=AdminController.listDevices),
    route(
        path="/api/assignments/start",
        methods=["POST"],
        handler=AdminController.startAssignment,
    ),
    route(
        path="/api/assignments",
        methods=["GET"],
        handler=AdminController.getAssignment,
    ),
    route(
        path="/api/assignments/cancel",
        methods=["POST"],
        handler=AdminController.cancelAssignment,
    ),
    route(path="/api/auth/login", methods=["POST"], handler=AuthController.login),
    route(path="/api/auth/me", methods=["GET"], handler=AuthController.me),
]

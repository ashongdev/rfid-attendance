"""
Dreema Application Entry Routes
This file defines the root routing table for the application.
"""

from controllers.usersController import UsersController
from dreema.routing import route

# defining all routes coming from the controllers
routes = [
    # creating single routes
    route.post("/api/attendance", UsersController.attendance),
]

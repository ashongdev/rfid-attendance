import controllers.adminController as Admin
import controllers.scanController as Scan

routes = [
    route(path="/api/attendance", methods=["POST"], handler=Scan.ScanController.scan),
    route(
        path="/api/people", methods=["POST"], handler=Admin.AdminController.createPerson
    ),
    route(
        path="/api/people", methods=["GET"], handler=Admin.AdminController.listPeople
    ),
    route(
        path="/api/devices", methods=["GET"], handler=Admin.AdminController.listDevices
    ),
    route(
        path="/api/assignments",
        methods=["POST"],
        handler=Admin.AdminController.startAssignment,
    ),
    route(
        path="/api/assignments",
        methods=["GET"],
        handler=Admin.AdminController.getAssignment,
    ),
    route(
        path="/api/assignments/cancel",
        methods=["POST"],
        handler=Admin.AdminController.cancelAssignment,
    ),
]

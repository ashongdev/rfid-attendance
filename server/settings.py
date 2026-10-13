ENVIRONMENT = "local"
SERVER_PORT = 8888

CORS = {
    "allowedOrigins": ["*"],
    "allowedMethods": ["GET", "POST", "PUT", "DELETE", "PATCH"],
    "notAllowedHeaders": [],
    "allowCredentials": True,
}

FILES = {"maxUploadSize": 1024 * 1000, "allowedFiles": ["jpg", "jpeg", "png", "pdf"]}

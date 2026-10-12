# environment
ENVIRONMENT = "local"
SERVER_PORT = 8888

# databases settings
DATABASES = {
    "app": {
        "type": "mysql",
        "host": "localhost",
        "port": 3306,
        "database": "test_mysql",
    },
    "system": {
        "type": "mongo",
        "host": "localhost",
        "port": 27017,
        "database": "test_mongo",
    },
}

# cors settings
CORS = {
    "allowedOrigins": ["*"],
    "allowedMethods": ["GET", "POST", "PUT", "DELETE"],
    "notAllowedHeaders": [],
    "allowCredentials": True,
}


# files settings
FILES = {
    "maxUploadSize": 10,  # size in bytes
    "allowedFiles": ["pdf"],
}

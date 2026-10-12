from .usersModel import UsersModel
MODELS = {
        'users': UsersModel(),
    }


def getModel(key):
    return MODELS.get(key, None)
    
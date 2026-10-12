from dreema.orm import database

class UsersModel(database.Database):
    #specify table or document name here
    tablename = 'users_table' 

     # system uses default connection type if not specified
    def __init__(self, connection="default"):
        super().__init__(connection=connection)
        self.setTable(self.tablename)
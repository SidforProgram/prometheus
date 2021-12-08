import os
from pydantic.types import NonPositiveFloat

class Files(object):
    def __init__(self,path="./"):
        self.path = str(path)
        # self.files = list()
        self.rootpath = os.getcwd()



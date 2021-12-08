# FastAPI $uvicorn Fast:app --reload <-Debug 模式
from os import chdir, getenv
from pydantic import BaseModel,Field
from fastapi import FastAPI, Path, HTTPException
from starlette.requests import Request
from json import JSONDecodeError
from fastapi.middleware.cors import CORSMiddleware
from core.fclass import Files
import core.curd as curd

from dotenv import load_dotenv
load_dotenv()
File_Root_Path = getenv("File_Root_Path")
Flists = Files(File_Root_Path)

class patch(BaseModel):
    yml : str = Field(...,
                     title="Patch content",
                     description="Patch the content of this yml",
                     example="num: 1\ntest1: test1\n")

class add(BaseModel):
    add_path : str = Field(...,
                            title = "Add File Path",
                            description = "The path will save, Can use absolute or relative path, The root of relative was set in env",
                            example = "./")
    add_name : str = Field(...,
                            title = "Add File Name",
                            description = "The name of file, Need add file extension",
                            example = "addtest.yml")
    yml : str = Field(...,
                     title = "Add content",
                     description = "What the content of this yml file",
                     example = "num: 1\ntest1: test1\n")

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/yml/api")
def Get_Files():
    result = curd.Get_Files(Flists.path)
    if result:
        return result
    elif len(result) == 0:
        return {"message":"There are,t have any yml file"}
    else:
        return {"message":"Can,t get the Files"}

@app.get("/yml/api/{filenumber}")
def Get_File_Info(filenumber:int=Path(..., title="The number of the File", ge=1)):
    result = curd.Get_File_info(filenumber)
    chdir(Flists.rootpath)
    if(result):
        return result
    else:
        message = "Get File is not success, Maybe it isn,t exist"
        raise HTTPException(status_code=404,detail=message)


@app.delete("/yml/api/{filenumber}")
def Delete_File(filenumber:int=Path(..., title="The number of the File", ge=1)):
    result = curd.Delete_File(filenumber)
    chdir(Flists.rootpath)
    if result:
        return {"message":"The file {0} is deleted".format(filenumber)}
    message = "Delete is not success, Maybe The file isn,t exist"
    raise HTTPException(status_code=404,detail=message)

@app.patch("/yml/api/{filenumber}")
async def Patch_File(filenumber:int=Path(..., title="The number of the File", ge=1),
                     patch: patch = None): 
    # 更新後內容不太一樣
    try:
        result=False
        # Fcontent = patch.json()
        # print(patch.yml)
        # print(Fcontent["yml"])
        result = curd.Patch_File(filenumber,patch.yml)
        chdir(Flists.rootpath)
        if result:
            message = "The file is updata , You can check the filenumber : {0} ".format(filenumber)
            return {"message":message}
        else:
            message = "Get File is not success, Maybe it isn,t exist"
            raise HTTPException(status_code=404,detail=message)

    except JSONDecodeError:
        message = "Received data is not a valid JSON"
        return {"message": message}

    # result = None
    # try:
    #     # Fcontent = await request.json()
    #     # Filelist = (i for i in curd.Get_Files(Flists.path) if i["filenumber"] > 0)
    #     for i in Filelist:
    #         if(i['filenumber']==filenumber):
    #             result = curd.Patch_File(i['fpath'],i['fname'],Fcontent)
    #             message = "The {0}/{1} is updata , You can check the filenumber : {2} ".format(i['fpath'],i['fname'],filenumber)
    #             chdir(Flists.rootpath)
    #             if result:
    #                 return {"message":message}
    #     message = "Get File is not success, Maybe it isn,t exist"
    #     raise HTTPException(status_code=404,detail=message)
    # except JSONDecodeError:
    #     message = "Received data is not a valid JSON"
    #     return {"message": message}
    

@app.post("/yml/api")
def Post_File(add: add):
    result = curd.Post_File(add.add_path,add.add_name,add.yml)
    chdir(Flists.rootpath)
    if(result==1):
        return {"message":"The file is exist, You can use patch to updata it"}
    elif(result==2):
        return {"message":"This post is success"}
    else:
        return {"message":"The post action is fail"}

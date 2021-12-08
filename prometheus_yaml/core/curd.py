import yaml
import os
import sys

# from fast import Flists

from .parent_tree import folder_tree

Filelist = list()

def Get_Files(fpath="./"):
    global Filelist
    filenumber = 1
    
    folder_list_n2i = dict()# 資料夾代表的編號，{filename:id} 
    folder_parent_relation = dict()# 儲存誰是此資料夾的父資料夾，{pwd:parent}
    folder_rank = dict()# 資料夾階層
    folder_purely_name = dict()# 資料夾名稱（去路徑）
    updata_folder_list_n2i = dict()# 用於其他函式路徑切換
    folder_tree(fpath,folder_list_n2i,folder_parent_relation,folder_rank,folder_purely_name,updata_folder_list_n2i)


    templist = list()
    for root, dirs, files in os.walk(fpath):
        data = {
            "filenumber":folder_list_n2i[root],
            "parent":folder_parent_relation[root],
            "fpath":folder_rank[root],
            "fname":folder_purely_name[root]
        }
        templist.append(data)
        for file in files:
            if(".yml" in file):
                data = {
                    "filenumber":filenumber,
                    "parent":folder_list_n2i[root],
                    "fpath":root,
                    "fname":file 
                }
                templist.append(data)
                filenumber += 1
    Filelist = [a for a in templist if(a["filenumber"] > 0)]
    return templist

def Get_File_info(filenumber):
    global Filelist
    for i in Filelist:
        if(i['filenumber']==filenumber):
            fpath = i['fpath']
            fname = i['fname']
            break
    os.chdir(fpath)
    if os.path.exists(fname):
        with open(fname,"r") as f:
            content = f.read()
            return content
    else:
        return False
    
def Delete_File(filenumber):
    global Filelist
    for i in Filelist:
        if(i['filenumber']==filenumber):
            fpath = i['fpath']
            fname = i['fname']
            break
    os.chdir(fpath)
    if os.path.exists(fname):
        os.remove(fname)
        return True
    else:
        return False

def Patch_File(filenumber,content):
    global Filelist
    for i in Filelist:
        if(i['filenumber']==filenumber):
            fpath = i['fpath']
            fname = i['fname']
            break
    # yml_content = yaml.safe_dump(content,sort_keys=False)
    os.chdir(fpath)
    if os.path.exists(fname):
        with open(fname,"w") as f:
            f.write(content)
            return True
    else:
        return False

def Post_File(fpath,fname,content):
    try:
        # yml_content = yaml.safe_dump(content,sort_keys=False)
        os.chdir(fpath)
        if os.path.exists(fname):
            return 1
        else:
            with open(fname,"w") as f:
                f.write(content)
                return 2
    except:
        print(sys.exc_info())
        return 3



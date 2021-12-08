import os

# def files_tree(startpath,file_list_n2i,file_list_i2n):
#     list_num = 1
    # parent_relation[startpath] = 0
    # for root, dirs, files in os.walk(startpath):
    #     if (root not in file_list_n2i):
    #         file_list_n2i[root] = list_num 
    #         file_list_i2n[list_num] = root
    #         list_num += 1 
        # for i in dirs:
            # if(root[-1]!='/'):
            #     parent_relation[root+"/"+i] = parent_list_n2i[root]
            # else:
            #     parent_relation[root+i] = parent_list_n2i[root]

def folder_tree(startpath,folder_list_n2i,folder_parent_relation,folder_rank,folder_purely_name,updata_folder_list_n2i):
    list_num = -2 # -1固定為根目錄
    folder_list_n2i[startpath] = -1# 代表編號
    folder_parent_relation[startpath] = 0# 根目錄，父層為 0
    folder_rank[startpath] = -1# 代表階層
    folder_purely_name[startpath] = startpath
    updata_folder_list_n2i[-1] = startpath# 編號對照回路徑
    for root, dirs, files in os.walk(startpath):
        # 將 folder 編號
        if (root not in folder_list_n2i):
            folder_list_n2i[root] = list_num
            updata_folder_list_n2i[list_num] = root
            list_num -= 1
        # 建立 folder 之間的階層關係
        for i in dirs:
            if(root[-1]!='/'):
                folder_parent_relation[root+"/"+i] = folder_list_n2i[root]
                folder_rank[root+"/"+i] = folder_rank[root]-1
                folder_purely_name[root+"/"+i] = i
            else:
                folder_parent_relation[root+i] = folder_list_n2i[root]
                folder_rank[root+i] = folder_rank[root]-1
                folder_purely_name[root+i] = i
                
import os 

def get_file_tree(repo_path:str ) : 
    file_tree=""
    
    for root , dirs , files in os.walk(repo_path) : 
        relative_path = os.path.relpath(root , repo_path)
        depth = 0 if relative_path== "." else relative_path.count(os.sep) + 1
        indent = "  " * depth
        file_tree+= root + "\n"
        for directory  in dirs : 
           file_tree+= indent +  "|__" + directory  + "\n"
        for file in files : 
          file_tree += indent + "|__" + file + "\n"



    return file_tree

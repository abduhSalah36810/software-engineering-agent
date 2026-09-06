
import subprocess
import os 
from dotenv import load_dotenv
load_dotenv()

def clone_repo(url : str ) : 
        print("Starting to clone the repo.... ")
        base_path = os.getenv("PATH_TO_CLONED_REPO")
        repo_name= url.rstrip("/").rsplit("/")[-1].removesuffix(".git") 
        repo_path = os.path.join(base_path,repo_name)
        result= subprocess.run(["git" ,  "clone" ,  url , repo_path ] , capture_output=True , text=True)
        if result.returncode == 0 : 
           print("cloned successfully ✅✅")
        else : 
           print("clone failed ❌❌")
           print(result.stderr)
        return repo_path
          

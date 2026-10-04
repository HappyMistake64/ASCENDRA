import os,shutil,subprocess,tempfile,time
from pathlib import Path
ALLOWED_EXEC={'python','python3','pytest'}
class SandboxViolation(RuntimeError):pass
class Sandbox:
    def __init__(self,work_root:Path):self.work_root=work_root;work_root.mkdir(parents=True,exist_ok=True)
    def create(self,task):
        p=Path(tempfile.mkdtemp(prefix=f'{task.id}-',dir=self.work_root));shutil.copytree(task.source_dir,p,dirs_exist_ok=True);return p
    def run(self,cwd,command,timeout_s):
        if not command or Path(command[0]).name not in ALLOWED_EXEC:raise SandboxViolation(f'command not allowed: {command}')
        start=time.perf_counter();env={'PATH':os.environ.get('PATH',''),'PYTHONPATH':str(cwd),'HOME':str(cwd)}
        try:
            cp=subprocess.run(command,cwd=cwd,text=True,capture_output=True,timeout=timeout_s,env=env)
            return cp.returncode,cp.stdout[-12000:],cp.stderr[-12000:],time.perf_counter()-start
        except subprocess.TimeoutExpired:return 124,'','timeout',time.perf_counter()-start
    def cleanup(self,p):shutil.rmtree(p,ignore_errors=True)

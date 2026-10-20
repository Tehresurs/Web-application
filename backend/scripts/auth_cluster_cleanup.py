"""Cleanup only an owned cluster below an exact run directory."""
import shutil

def cleanup(cluster,run,base,stop,stopped):
    if cluster.resolve().parent!=run.resolve() or run.resolve().parent!=base.resolve():
        raise RuntimeError('Cleanup path outside owned run')
    attempts=0
    if not stopped():
        for _ in range(2):
            attempts+=1
            try:stop()
            except Exception:pass
            if stopped():break
    if not stopped():
        return {'removed':False,'stop_attempts':attempts,'error':'Cluster still running; directory preserved'}
    if cluster.exists():shutil.rmtree(cluster)
    return {'removed':not cluster.exists(),'stop_attempts':attempts,'error':None}

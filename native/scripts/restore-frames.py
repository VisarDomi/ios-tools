"""Frame by frame, how much of a recorded relaunch differs from the screen as it was left
(restore-video.sh). Needs ffmpeg and Pillow."""
import sys,glob,os,subprocess
from PIL import Image, ImageChops
d=sys.argv[1]; fps=int(sys.argv[2]) if len(sys.argv)>2 else 10
subprocess.run(["ffmpeg","-loglevel","error","-y","-i",f"{d}/launch.mp4","-vf",f"fps={fps},scale=440:-1",f"{d}/v-%04d.png"],check=True)
before=Image.open(f"{d}/before.png").convert("L").resize((440,956))
last=None
for f in sorted(glob.glob(f"{d}/v-*.png")):
    im=Image.open(f).convert("L").resize((440,956))
    diff=ImageChops.difference(before,im).point(lambda v:255 if v>24 else 0)
    pct=100*sum(1 for v in diff.getdata() if v)/(440*956)
    t=(int(os.path.basename(f)[2:6])-1)/fps
    line=f"{pct:5.1f}%"
    if line!=last: print(f"t={t:5.1f}s  differs {line}  box={diff.getbbox()}"); last=line

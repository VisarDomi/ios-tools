"""Frame by frame, how much of a recorded relaunch differs from the screen as it was left
(restore-video.sh). Needs ffmpeg and Pillow."""
import sys,glob,os,subprocess
from PIL import Image, ImageChops
d=sys.argv[1]; fps=int(sys.argv[2]) if len(sys.argv)>2 else 10
subprocess.run(["ffmpeg","-loglevel","error","-y","-i",f"{d}/launch.mp4","-vf",f"fps={fps},scale=440:-1",f"{d}/v-%04d.png"],check=True)
before=Image.open(f"{d}/before.png").convert("L").resize((440,956))
# iOS fades a launching app in: frames are scaled to the screen's brightness before comparing,
# so the fade does not count as a difference (content that is missing still does).
from PIL import ImageStat
target=ImageStat.Stat(before).mean[0]
def normalize(im):
    mean=ImageStat.Stat(im).mean[0]
    return im if mean < 1 else im.point(lambda v: min(255, int(v * target / mean)))
last=None
first_content=None
seen_launch=False
for f in sorted(glob.glob(f"{d}/v-*.png")):
    raw=Image.open(f).convert("L").resize((440,956))
    black=ImageStat.Stat(raw).mean[0] < 3
    im=normalize(raw)
    diff=ImageChops.difference(before,im).point(lambda v:255 if v>40 else 0)
    pct=100*sum(1 for v in diff.getdata() if v)/(440*956)
    t=(int(os.path.basename(f)[2:6])-1)/fps
    line=f"{pct:5.1f}%" + ("  (launch screen)" if black else "")
    seen_launch = seen_launch or black
    if first_content is None and not black and seen_launch: first_content=(t,pct)
    if line!=last: print(f"t={t:5.1f}s  differs {line}  box={diff.getbbox()}"); last=line
if first_content: print(f"first frame with content: t={first_content[0]:.1f}s, differs {first_content[1]:.1f}%")

"""Produce the brief's 512 px inspection image and measured sRGB histogram.

This does not relight, retouch, or replace the Blender render.
Requires Pillow and numpy; not needed for build_chapel.py.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image


def inspect(path):
    im=Image.open(path).convert("RGB")
    rgb=np.asarray(im,dtype=float)/255
    y=rgb@np.array([.2126,.7152,.0722])
    bins=[0,.02,.04,.08,.12,.2,.35,.6,1.00001]
    counts,_=np.histogram(y,bins=bins)
    report={"image":str(path),"size":list(im.size),
        "display_referred_luminance_mean":float(y.mean()),
        "display_referred_luminance_median":float(np.median(y)),
        "luminance_percentiles":dict(zip(["5","25","50","75","90","95","99"],
                                         np.percentile(y,[5,25,50,75,90,95,99]).tolist())),
        "dark_pixels_below_0.12_percent":float((y<.12).mean()*100),
        "warm_pixels_over_0.2_percent":float(((y>.2)&(rgb[:,:,0]>1.4*rgb[:,:,2])).mean()*100),
        "all_channels_clipped_percent":float((rgb.min(axis=2)>=254/255).mean()*100),
        "histogram_edges":bins,"histogram_percent":(counts/y.size*100).tolist(),
        "note":"Luminance measured on the displayed AgX PNG, not scene-linear radiance. Thresholds are explicitly defined; visual inspection is still required."}
    out=path.parent/"qa";out.mkdir(exist_ok=True)
    thumb=im.copy();thumb.thumbnail((512,512),Image.Resampling.LANCZOS)
    thumb.save(out/(path.stem+"_512.png"))
    (out/(path.stem+"_histogram.json")).write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("images",nargs="+",type=Path)
    for file in p.parse_args().images: inspect(file.resolve())

"""Generate train_helmet_colab.ipynb (embeds prepare_helmet_crops.py so the notebook is standalone).

    python build_notebook.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
PREP = (HERE / "prepare_helmet_crops.py").read_text(encoding="utf-8")

cells = []


def md(s):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": s.strip("\n").splitlines(keepends=True)})


def code(s):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                  "source": s.strip("\n").splitlines(keepends=True)})


md("""
# RoadGuard AI — helmet classifier training

Trains a **YOLO11 classification model** that looks at a crop of a tracked motorcycle (plus its
riders) and predicts `helmet` (all riders helmeted) or `no_helmet` (at least one rider without).
RoadGuard runs it on each motorcycle track every few frames and votes across the track.

**Data:** [HELMET dataset](https://osf.io/4pwj8/) — Lin & Siebert, *Helmet use detection of tracked
motorcycles using CNN-based multi-task learning*, IEEE Access 2020. **CC BY 4.0.** 910 roadside
traffic clips from Myanmar, 10,006 tracked motorcycles with per-rider helmet labels. The official
per-clip train/val/test split is used, so no clip leaks across splits.

**Resumable:** on Colab the finished crop parts and training checkpoints are saved to Google Drive
(`MyDrive/roadguard_helmet`). If the session disconnects, reconnect and *Run all* again — it
restores the prepared parts and continues training from the last completed epoch.

**Runtime:** Colab → *Runtime → Change runtime type → T4 GPU* (or Kaggle with GPU + Internet on).
All 7 parts ≈ 28 GB are streamed one at a time (download → unzip → crop → delete), so peak disk is
~10 GB. Expect ~15–25 min data prep + ~20–40 min training on a T4. Use fewer `PARTS` for a quicker run.
""")

code("""
!nvidia-smi -L || echo "No GPU — switch the runtime to GPU"
%pip install -q "ultralytics>=8.3"
""")

code("""
import os, shutil, subprocess, zipfile, json, time
from pathlib import Path

ON_KAGGLE = os.path.exists('/kaggle')
WORK = Path('/kaggle/working/helmet' if ON_KAGGLE else '/content/helmet')

# Resume support: Colab wipes /content when the session disconnects, so checkpoints and the
# finished crop parts are kept in Google Drive. Re-running the notebook after a disconnect skips
# parts already prepared and resumes training from the last completed epoch.
USE_DRIVE = not ON_KAGGLE
if USE_DRIVE:
    from google.colab import drive
    drive.mount('/content/drive')
    SAVE = Path('/content/drive/MyDrive/roadguard_helmet')
else:
    SAVE = WORK / 'persist'   # Kaggle: /kaggle/working survives "Save Version" runs
SAVE.mkdir(parents=True, exist_ok=True)

PARTS = ['part_1', 'part_2', 'part_3', 'part_4', 'part_5', 'part_6', 'part_7']  # fewer = faster
STRIDE = 5            # sample every Nth annotated frame per motorcycle track (10 fps source)
MODEL = 'yolo11s-cls.pt'
IMGSZ = 224           # must match `rules.helmet.imgsz` in the RoadGuard camera config
EPOCHS = 30
BATCH = 256

OSF = {  # osf.io/4pwj8 download ids
    'annotation.zip': 'buh57', 'data_split.csv': 'q7rmb',
    'part_1': '452nq', 'part_2': 'muzgb', 'part_3': '9dmw3', 'part_4': '39ynb',
    'part_5': 'v3rch', 'part_6': 'jyg9s', 'part_7': '6h5ka',
}
RAW, CROPS = WORK / 'raw', WORK / 'helmet_cls'
RAW.mkdir(parents=True, exist_ok=True)

def fetch(key, dest):
    if not dest.exists():
        subprocess.run(['wget', '-q', '--show-progress', '-O', str(dest), f'https://osf.io/download/{OSF[key]}/'], check=True)
    return dest

fetch('data_split.csv', RAW / 'data_split.csv')
with zipfile.ZipFile(fetch('annotation.zip', RAW / 'annotation.zip')) as z:
    z.extractall(RAW / 'annotation')
print(sum(1 for _ in (RAW / 'annotation').rglob('*.csv')), 'annotation files')
""")

md("### Crop extraction (same script as `backend/training/prepare_helmet_crops.py`)")
code("%%writefile prepare_helmet_crops.py\n" + PREP)

code("""
from prepare_helmet_crops import build

SAVED_PARTS = SAVE / 'crops'          # one zip of finished crops per part (resume point)
SAVED_PARTS.mkdir(exist_ok=True)
for part in PARTS:
    saved = SAVED_PARTS / f'{part}.zip'
    if saved.exists():                 # prepared in an earlier session: just restore
        with zipfile.ZipFile(saved) as z:
            z.extractall(CROPS)
        print(f'{part}: restored from {saved}')
        continue
    t0 = time.time()
    zpath = fetch(part, RAW / f'{part}.zip')
    with zipfile.ZipFile(zpath) as z:
        z.extractall(RAW / 'images')
    zpath.unlink()
    tmp = WORK / 'tmp_part'
    shutil.rmtree(tmp, ignore_errors=True)
    stats = build(RAW / 'images', RAW / 'annotation', RAW / 'data_split.csv', tmp, stride=STRIDE)
    shutil.rmtree(RAW / 'images')          # free disk before the next part
    shutil.make_archive(str(saved.with_suffix('')), 'zip', tmp)   # persist, then merge
    shutil.copytree(tmp, CROPS, dirs_exist_ok=True)
    shutil.rmtree(tmp)
    print(f'{part}: {stats}  ({time.time() - t0:.0f}s)')

for split in ('train', 'val', 'test'):
    print(split, {c: len(list((CROPS / split / c).glob('*.jpg'))) for c in ('helmet', 'no_helmet')})
""")

code("""
# Look at a few crops of each class
import random, matplotlib.pyplot as plt
from PIL import Image
fig, axes = plt.subplots(2, 8, figsize=(16, 5))
for row, cls in enumerate(['helmet', 'no_helmet']):
    files = random.Random(0).sample(sorted((CROPS / 'train' / cls).glob('*.jpg')), 8)
    for ax, f in zip(axes[row], files):
        ax.imshow(Image.open(f)); ax.set_title(cls, fontsize=9); ax.axis('off')
plt.tight_layout(); plt.show()
""")

md("### Train")
code("""
import torch
from ultralytics import YOLO

RUN = SAVE / 'runs' / 'helmet_cls'          # checkpoints live in Drive → survive disconnects
LAST, BEST = RUN / 'weights' / 'last.pt', RUN / 'weights' / 'best.pt'
WORKERS = min(8, os.cpu_count() or 2)       # parallel data-loading processes

state = 'fresh'
if LAST.exists():
    ck = torch.load(LAST, map_location='cpu', weights_only=False)
    state = 'finished' if ck.get('epoch', -1) == -1 or ck.get('optimizer') is None else 'resume'

if state == 'resume':
    print(f"Resuming from {LAST} (completed epoch {ck['epoch'] + 1})")
    YOLO(str(LAST)).train(resume=True, workers=WORKERS, cache='ram')
elif state == 'fresh':
    YOLO(MODEL).train(
        data=str(CROPS), epochs=EPOCHS, imgsz=IMGSZ, batch=BATCH, patience=8,
        project=str(RUN.parent), name=RUN.name, exist_ok=True,
        cos_lr=True, dropout=0.1, fliplr=0.5, hsv_v=0.4, scale=0.1, erasing=0.0,  # keep riders' heads in frame
        workers=WORKERS, cache='ram', seed=0, deterministic=True,
    )
else:
    print('Training already finished in an earlier session — delete', RUN, 'to retrain.')
print(BEST, BEST.exists())
""")

md("### Evaluate on the held-out test clips\n\nCrop-level metrics, then **track-level** metrics (average probability over all crops of a "
   "motorcycle), which is closer to how RoadGuard votes.")
code("""
from collections import defaultdict
import numpy as np

best = YOLO(BEST)
names = best.names; NO = [k for k, v in names.items() if v == 'no_helmet'][0]
y_true, y_prob, tracks = [], [], defaultdict(list)
for cls in ('helmet', 'no_helmet'):
    files = sorted((CROPS / 'test' / cls).glob('*.jpg'))
    for i in range(0, len(files), 256):
        for f, r in zip(files[i:i+256], best.predict([str(f) for f in files[i:i+256]], imgsz=IMGSZ, verbose=False)):
            p = float(r.probs.data[NO])
            y_true.append(cls == 'no_helmet'); y_prob.append(p)
            clip_track = f.stem.rsplit('_', 1)[0]
            tracks[clip_track].append((cls == 'no_helmet', p))

def report(truth, prob, label, thr=0.5):
    truth, pred = np.array(truth), np.array(prob) >= thr
    tp, fp = int((pred & truth).sum()), int((pred & ~truth).sum())
    fn, tn = int((~pred & truth).sum()), int((~pred & ~truth).sum())
    prec, rec = tp / max(1, tp + fp), tp / max(1, tp + fn)
    print(f'{label:6s} n={len(truth):6d}  acc={(tp + tn) / len(truth):.3f}  '
          f'no_helmet precision={prec:.3f} recall={rec:.3f} F1={2 * prec * rec / max(1e-9, prec + rec):.3f}')
    return dict(n=len(truth), acc=(tp + tn) / len(truth), precision=prec, recall=rec, tp=tp, fp=fp, fn=fn, tn=tn)

crop_m = report(y_true, y_prob, 'crops')
track_m = report([v[0][0] for v in tracks.values()], [np.mean([p for _, p in v]) for v in tracks.values()], 'tracks')
""")

md("### Export for RoadGuard")
code("""
out = WORK / 'helmet_cls.pt'
shutil.copy(BEST, out)
(WORK / 'helmet_cls_metrics.json').write_text(json.dumps({
    'model': MODEL, 'imgsz': IMGSZ, 'epochs': EPOCHS, 'parts': PARTS, 'stride': STRIDE,
    'test_crops': crop_m, 'test_tracks': track_m, 'dataset': 'HELMET (osf.io/4pwj8), CC BY 4.0',
}, indent=2))
print('Saved', out)
try:
    from google.colab import files
    files.download(str(out)); files.download(str(WORK / 'helmet_cls_metrics.json'))
except ImportError:
    print('On Kaggle: download from the Output panel (/kaggle/working/helmet).')
""")

md("""
### Use it in RoadGuard

1. Put `helmet_cls.pt` in `backend/models/`.
2. In the camera config (`backend/config/cameras/<camera>.yaml`):

```yaml
rules:
  helmet:
    enabled: true
    model: models/helmet_cls.pt
    imgsz: 224        # same as IMGSZ above
    min_conf: 0.6     # abstain on uncertain crops
    min_votes: 3      # no_helmet votes needed per motorcycle track
```

The model was trained on Myanmar roadside footage; expect some drop on very different camera
angles or regions — fine-tune with your own labelled crops (same folder layout) if needed.
""")

nb = {"cells": cells, "metadata": {"accelerator": "GPU", "kernelspec": {"display_name": "Python 3", "name": "python3"},
                                  "language_info": {"name": "python"}, "colab": {"provenance": [], "gpuType": "T4"}},
      "nbformat": 4, "nbformat_minor": 5}
(HERE / "train_helmet_colab.ipynb").write_text(json.dumps(nb, indent=1), encoding="utf-8")
print("wrote", HERE / "train_helmet_colab.ipynb")

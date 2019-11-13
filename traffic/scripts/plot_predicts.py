

import sys,os
sys.path.append(os.getcwd())

import torch
import argparse
import numpy as np
import cv2
import os
import matplotlib
import matplotlib.pyplot as plt
from collections import defaultdict
from traffic.utils.drawing import random_colors, display_instances, display_trace
from maskrcnn_benchmark.structures.bounding_box import BoxList
from collections import defaultdict, deque
from maskrcnn_benchmark.modeling.roi_heads.mask_head.inference import Masker
matplotlib.use('Agg')

parser = argparse.ArgumentParser(description="Render pretty images with detection results")
parser.add_argument(
    "--video-file", metavar="FILE", help="path to the raw .mp4 video (no preprocessing)", type=str, required=True
)
parser.add_argument(
    "--tracklets", metavar="FOLDER", help=".pth file with tracklets", type=str, required=True
)
parser.add_argument(
    "--save-to", metavar="FOLDER", help="target folder for resilts", type=str, required=True
)
args = parser.parse_args()

CLASS_NAMES = {
     1: "car",
     2: "trolleybus",
     3: "tram",
     4: "truck",
     5: "bus",
     6: "van"
}

masker = Masker(threshold=0.75)

def project_masks(bboxlist):
    if bboxlist.has_field("mask"):
        masks = bboxlist.get_field("mask")
        masks = masker([masks], [bboxlist])[0]
        bboxlist.add_field("mask", masks)
    return bboxlist

video_file = args.video_file
folder = args.save_to
os.makedirs(folder, exist_ok=True)

stream = cv2.VideoCapture(video_file)

# load tracklets and build index
tracklets = torch.load(args.tracklets)
objects_on_frame = defaultdict(list)
ind = 0
for x in tracklets:
    x['index'] = ind
    assert x['appeared'] <= x['lost']
    ind += 1
    appeared, lost = x['appeared'], x['lost']
    for i in range(appeared, lost+1):
        objects_on_frame[i].append(x)

# add color to objects
colors_generator = random_colors(N=5000, seed=123)   # Not well suitable, but works
for x in tracklets:
    x['color'] = colors_generator[x['index'] % 5000]

DPI = plt.rcParams['figure.dpi']
FRAME_ID = -1

# centers of the objects, id(x) -> [matplotlib Circle, ...., most recent center] at most N frames
HISTORY = defaultdict(lambda *args: {"centers": deque(), "color": None})

plt.figure(figsize=(1920 / DPI, 1080 / DPI), dpi=DPI)
plt.subplots_adjust(bottom=0, right=1, top=1, left=0)

# ret, frame = stream.read()
# ret, frame = stream.read()
while stream.isOpened():
    ret, frame = stream.read()
    FRAME_ID += 1
    print("Current frame ", FRAME_ID)

    if not ret:
        print("Failed to read frame. Terminating further processing")
        break

    assert frame.ndim == 3 and frame.shape[-1] == 3
    H, W = frame.shape[:2]


    # load objects for current frame
    boxes, masks, labels, index, colors = [], [], [], [], []
    for x in objects_on_frame[FRAME_ID]:
        i = FRAME_ID - x['appeared']
        boxes.append(x['box'][i])
        masks.append(x['mask'][i])
        labels.append(x['label'])
        index.append(x['index'])
        colors.append(x['color'])

    if len(boxes) == 0:
        continue

    # print(torch.stack(boxes).shape)
    # print(torch.stack(masks).shape)
    # print(torch.tensor(labels).shape)
    # print(torch.tensor(index).shape)

    detections = BoxList(torch.stack(boxes), (W, H))
    detections.add_field('mask', torch.stack(masks))
    detections.add_field('labels', torch.tensor(labels))
    detections.add_field('index', torch.tensor(index))

    if detections.get_field('mask').dim() != 4:
        detections.get_field('mask').data = detections.get_field('mask').unsqueeze(1)
    detections = project_masks(detections)

    ax = plt.gca()
    ax.get_xaxis().set_visible(False)
    ax.get_yaxis().set_visible(False)

    # update history
    centers = np.zeros((len(detections), 2), dtype=np.float)
    centers[:, 0] = (detections.bbox[:, 0] + detections.bbox[:, 2]) / 2
    centers[:, 1] = (detections.bbox[:, 1] + detections.bbox[:, 3]) / 2
    updated = {ind: False for ind in HISTORY.keys()}
    for i in range(len(detections)):
        ind = detections.get_field('index')[i]
        ind = int(ind)
        center = centers[i]
        if ind not in HISTORY:
            HISTORY[ind]['color'] = colors[i]
        HISTORY[ind]['centers'].append(center)
        if len(HISTORY[ind]['centers']) > 50:
            HISTORY[ind]['centers'].popleft() # keep only last N objects
        updated[ind] = True

    # drop last prediction of the lost objects
    for k, v in updated.items():
        if v:
            continue
        HISTORY[k]['centers'].popleft()
        if len(HISTORY[k]['centers']) == 0:
            del HISTORY[k]

    # BGR -> RGB
    frame = frame[:, :, [2, 1, 0]]
    display_instances(frame, detections, CLASS_NAMES, ax, colors=colors)
    display_trace(HISTORY, ax, alpha=0.5)
    plt.savefig(os.path.join(folder, f'image-{FRAME_ID}.png'), bbox_inches='tight',
                pad_inches=0, dpi=DPI)


    plt.clf()
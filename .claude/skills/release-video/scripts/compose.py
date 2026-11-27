"""Turn a scene's screencast frames into a 1080p30 clip: cut holds, fit to narration, apply smooth zooms."""

import bisect
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import BADGE_Y, FPS, OUT_H, OUT_W, STAGE, VERTICAL, ffmpeg, read_json, write_json


def ease(k: float) -> float:
    """
    Ease-in-out cubic.

    :param k: float, progress 0..1
    :return: float, eased progress
    """
    k = min(max(k, 0.0), 1.0)
    return 4 * k**3 if k < 0.5 else 1 - (-2 * k + 2) ** 3 / 2


class Timeline:
    """Real → virtual (holds removed) → output (tail compressed) time mapping for one scene."""

    def __init__(
        self, tl: dict, sync_end: float, tail: float, max_speedup: float
    ) -> None:
        """
        Build the mapping from a recorder timeline.

        :param tl: dict, timeline.json content
        :param sync_end: float, virtual second where the narration ends
        :param tail: float, seconds allowed after the narration
        :param max_speedup: float, maximum speed-up of the overrun tail
        :return: None
        """
        self.t0, self.holds = tl['t0'], sorted(tl['holds'])
        self.length = self.virtual(tl['end'])
        self.sync_end = sync_end
        over = max(self.length - sync_end, 0.0)
        self.speed = min(max(over / tail, 1.0), max_speedup) if tail > 0 else 1.0
        self.out_length = (
            sync_end + over / self.speed if self.length > sync_end else self.length
        )

    def virtual(self, ts: float) -> float:
        """
        Map a wall-clock timestamp to clip time; anything inside a hold collapses to the hold start.

        :param ts: float, wall-clock seconds
        :return: float, virtual seconds
        """
        cut = 0.0
        for a, b in self.holds:
            if ts >= b:
                cut += b - a
            elif ts > a:
                cut += ts - a
        return max(ts - self.t0 - cut, 0.0)

    def to_out(self, tv: float) -> float:
        """
        Map virtual time to output time (tail after the narration is sped up).

        :param tv: float, virtual seconds
        :return: float, output seconds
        """
        return (
            tv
            if tv <= self.sync_end
            else self.sync_end + (tv - self.sync_end) / self.speed
        )

    def to_virtual(self, to: float) -> float:
        """
        Inverse of to_out.

        :param to: float, output seconds
        :return: float, virtual seconds
        """
        return (
            to
            if to <= self.sync_end
            else self.sync_end + (to - self.sync_end) * self.speed
        )


def crop_track(
    events: list[dict], tl: Timeline, size: tuple[int, int], scale: float
) -> list[tuple]:
    """
    Turn zoom / zoom_out events into keyframes of the crop rectangle (frame pixels).

    :param events: list[dict], recorder events
    :param tl: Timeline, time mapping
    :param size: tuple[int, int], captured frame size (W, H)
    :param scale: float, device scale factor (CSS px → frame px)
    :return: list[tuple], (t_out_start, dur, rect_from, rect_to)
    """
    W, H = size
    full = (0.0, 0.0, float(W), float(H))
    cur, keys = full, []
    for ev in events:
        if ev['type'] not in ('zoom', 'zoom_out'):
            continue
        if ev['type'] == 'zoom':
            b, s = ev['box'], max(ev.get('scale', 1.3), 1.0)
            cx, cy = (b['x'] + b['width'] / 2) * scale, (
                b['y'] + b['height'] / 2
            ) * scale
            w, h = W / s, H / s
            x = min(max(cx - w / 2, 0), W - w)
            y = min(max(cy - h / 2, 0), H - h)
            target = (x, y, x + w, y + h)
        else:
            target = full
        keys.append((tl.to_out(ev['t']), ev.get('dur', 0.9), cur, target))
        cur = target
    return keys


ACTS = ('click', 'point', 'type')


def auto_zooms(events: list[dict], length: float, scale: float = 1.8) -> list[dict]:
    """
    Screen Studio-style zooms derived from the actions, for scenes without manual zooms.

    Each click / hover / fill zooms in just before the cursor starts moving; actions close
    together pan from one to the next instead of zooming out in between (out-then-in pumps);
    after the last one the view eases back to the full page if the scene has room for it.

    :param events: list[dict], recorder events (virtual time)
    :param length: float, scene length in virtual seconds
    :param scale: float, zoom factor
    :return: list[dict], events with the generated zoom / zoom_out added, sorted by time
    """
    if any(e['type'] in ('zoom', 'zoom_out') for e in events):
        return events
    acts = [e for e in events if e['type'] in ACTS and e.get('box')]
    if not acts:
        return events
    out, prev = [], None
    for e in acts:
        t = max(e.get('start', e['t']) - 0.1, 0.0)
        near = prev is not None and t - prev < 2.5
        # A hover usually opens a tooltip beside the point: zoom less so it stays in frame.
        s = scale if e['type'] != 'point' else max(scale * 0.8, 1.0)
        out.append({'t': t, 'type': 'zoom', 'box': e['box'], 'scale': s, 'dur': 0.55 if near else 0.7})
        prev = e['t']
    if prev + 1.6 + 0.8 <= length:
        out.append({'t': prev + 1.6, 'type': 'zoom_out', 'dur': 0.8})
    return sorted(events + out, key=lambda e: e['t'])


def sound_cues(events: list[dict], tl: Timeline) -> list[dict]:
    """
    Output times of the sound effects: a click on clicks, a pop on highlights and card items.

    The ring a click draws is the click's own highlight, so it gets no second sound.

    :param events: list[dict], recorder events
    :param tl: Timeline, time mapping
    :return: list[dict], [{'t', 'kind'}] in output seconds
    """
    cues = []
    for e in events:
        if e['type'] == 'click':
            kind = 'click'
        elif e['type'] == 'item' or (e['type'] == 'highlight' and e.get('by') != 'click'):
            kind = 'pop'
        else:
            continue
        t = tl.to_out(e['t'])
        if t <= tl.out_length:
            cues.append({'t': round(t, 3), 'kind': kind})
    return cues


def rect_at(keys: list[tuple], t: float, size: tuple[int, int]) -> tuple:
    """
    Crop rectangle at output time t.

    :param keys: list[tuple], keyframes from crop_track
    :param t: float, output seconds
    :param size: tuple[int, int], frame size
    :return: tuple, (x0, y0, x1, y1)
    """
    rect = (0.0, 0.0, float(size[0]), float(size[1]))
    for start, dur, a, b in keys:
        if t < start:
            break
        k = ease((t - start) / dur) if dur > 0 else 1.0
        rect = tuple(a[i] + (b[i] - a[i]) * k for i in range(4))
    return rect


def is_native(size: tuple[int, int]) -> bool:
    """
    Whether a frame already has the canvas's shape (a card recorded for 9:16), so it fills the canvas.

    :param size: tuple[int, int], captured frame size (W, H)
    :return: bool, True when the frame is drawn full-canvas instead of in the UI stage
    """
    return VERTICAL and abs(size[0] / size[1] - OUT_W / OUT_H) < 0.01


def stage_rect(
    rect: tuple, size: tuple[int, int], focus: tuple[float, float] = (0.5, 0.5)
) -> tuple:
    """
    Reshape a 16:9 crop to the vertical stage's aspect without cutting into it.

    The crop grows taller (never narrower) so a zoom target stays whole; only when the frame
    is too short for that does it shrink, which does cut the sides. A view that is nearly the
    whole page centres on `focus` instead of the page centre. Identity in 16:9.

    :param rect: tuple, (x0, y0, x1, y1) crop in frame pixels
    :param size: tuple[int, int], frame size (W, H)
    :param focus: tuple[float, float], point of interest as fractions of the frame
    :return: tuple, (x0, y0, x1, y1) crop with the stage's aspect
    """
    if not VERTICAL or is_native(size):
        return rect
    W, H = size
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    aspect = STAGE[2] / STAGE[3]
    w2, h2 = (w, w / aspect) if w / h > aspect else (h * aspect, h)
    k = min(1.0, W / w2, H / h2)
    w2, h2 = w2 * k, h2 * k
    full = min(max((w - 0.8 * W) / (0.2 * W), 0.0), 1.0)
    cx = (x0 + x1) / 2 * (1 - full) + focus[0] * W * full
    cy = (y0 + y1) / 2 * (1 - full) + focus[1] * H * full
    nx = max(min(cx - w2 / 2, W - w2), 0.0)
    ny = max(min(cy - h2 / 2, H - h2), 0.0)
    w2, h2 = min(w2, W - nx), min(h2, H - ny)
    return (nx, ny, nx + w2, ny + h2)


def draw_origin(size: tuple[int, int]) -> tuple[int, int, int]:
    """
    Where and how wide the cropped frame is drawn on the canvas.

    :param size: tuple[int, int], frame size
    :return: tuple[int, int, int], (x, y, width); height follows the crop's aspect
    """
    if is_native(size) or not VERTICAL:
        return 0, 0, OUT_W
    return STAGE[0], STAGE[1], STAGE[2]


def highlights(
    events: list[dict],
    tl: Timeline,
    keys: list[tuple],
    size: tuple[int, int],
    scale: float,
    focus: tuple[float, float] = (0.5, 0.5),
) -> list[dict]:
    """
    Highlighted boxes in output pixels with their visible interval (used to keep subtitles off them).

    :param events: list[dict], recorder events
    :param tl: Timeline, time mapping
    :param keys: list[tuple], crop keyframes
    :param size: tuple[int, int], frame size
    :param scale: float, device scale factor
    :return: list[dict], [{'start', 'end', 'box': [x0, y0, x1, y1]}]
    """
    out = []
    for i, ev in enumerate(events):
        if ev['type'] == 'type':
            # The text being typed is the subject: keep subtitles off the field while it fills.
            start, end = tl.to_out(ev.get('start', ev['t'])), tl.to_out(ev['t']) + 1.0
        elif ev['type'] != 'highlight':
            continue
        elif 'dur' in ev:
            start = tl.to_out(ev['t'])
            end = start + ev['dur']
        else:
            start = tl.to_out(ev['t'])
            nxt = next(
                (
                    e['t']
                    for e in events[i + 1 :]
                    if e['type'] in ('clear', 'highlight', 'zoom_out')
                ),
                None,
            )
            end = tl.to_out(nxt) if nxt is not None else tl.out_length
        x0, y0, x1, y1 = stage_rect(rect_at(keys, start + 1.0, size), size, focus)
        ox, oy, dw = draw_origin(size)
        f = dw / (x1 - x0)
        b = ev['box']
        bx = [ox + (b['x'] * scale - x0) * f, oy + (b['y'] * scale - y0) * f]
        bx += [bx[0] + b['width'] * scale * f, bx[1] + b['height'] * scale * f]
        out.append(
            {
                'start': round(start, 3),
                'end': round(end, 3),
                'box': [round(v) for v in bx],
            }
        )
    return out


def badge_image(text: str, cfg: dict) -> Image.Image:
    """
    Pill drawn in output pixels so it survives every zoom (a DOM badge is cropped away).

    :param text: str, badge text, e.g. the sample-data disclosure
    :param cfg: dict, full skill config (brand colours)
    :return: Image.Image, RGBA pill
    """
    # The landing's eyebrow pill: Martian Mono caps, violet tint and edge, live green dot.
    brand = cfg.get('brand', {})
    font = ImageFont.truetype(
        str(Path(__file__).resolve().parent.parent / 'assets' / 'fonts' / 'MartianMono-Variable.ttf'), 21
    )
    text = text.upper()
    left, top, right, bottom = font.getbbox(text)
    pad_x, pad_y, dot = 24, 16, 12
    w = right - left + pad_x * 2 + dot + 14
    h = bottom - top + pad_y * 2
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cta = brand.get('cta', '#7F3FE8').lstrip('#')
    edge = tuple(int(cta[i:i + 2], 16) for i in (0, 2, 4))
    d.rounded_rectangle(
        (0, 0, w - 1, h - 1), radius=h // 2, fill=(30, 24, 44, 235), outline=edge + (150,), width=2
    )
    cy = h // 2
    d.ellipse((pad_x, cy - dot // 2, pad_x + dot, cy + dot // 2), fill=brand.get('up', '#2AC77E'))
    d.text((pad_x + dot + 14 - left, pad_y - top), text, font=font, fill=(222, 215, 253, 255))
    return im


def compose_scene(
    clip_dir: Path,
    timing: dict,
    cfg: dict,
    hold: float | None = None,
    badge: str | None = None,
    auto_zoom: bool = True,
    focus: tuple[float, float] = (0.5, 0.5),
    src_dir: Path | None = None,
) -> dict:
    """
    Render clip.mp4 for one scene and write clip.json (duration, narration offset, highlights, sound cues).

    :param clip_dir: Path, scene directory with frames/ and timeline.json
    :param timing: dict, narration timing (duration)
    :param cfg: dict, full skill config
    :param hold: float | None, duration for scenes without narration
    :param badge: str | None, disclosure pill burned top-right on every frame (subtitles own the bottom; top-centre covered page titles)
    :param auto_zoom: bool, derive zooms from the actions when the scene has no manual ones
    :param focus: tuple[float, float], 9:16 only: point of interest (fractions of the frame) when the view is the whole page
    :param src_dir: Path | None, directory holding timeline.json and frames/ (default clip_dir; the 16:9 recording when re-framing)
    :return: dict, clip metadata
    """
    src_dir = src_dir or clip_dir
    clip_dir.mkdir(parents=True, exist_ok=True)
    tlj = read_json(src_dir / 'timeline.json')
    frames = tlj['frames']
    if not frames:
        sys.exit(f'{clip_dir.name}: no frames captured')
    v = cfg['video']
    lead, tail = v['scene_lead'], v['scene_tail']
    audio = timing.get('duration', hold or 2.5)
    tl = Timeline(tlj, lead + audio, tail, v['max_speedup'])
    target = lead + audio + tail
    # Actions that outlast the narration keep at most 1 s; the rest is trimmed.
    duration = min(max(target, tl.out_length), target + 1.0)
    with Image.open(src_dir / 'frames' / frames[0]['file']) as im:
        size = im.size
    scale = size[0] / tlj['viewport'][0]
    vts = [tl.virtual(f['ts']) for f in frames]
    order = sorted(range(len(frames)), key=lambda i: (vts[i], i))
    vts_sorted = [vts[i] for i in order]
    events = tlj['events']
    if auto_zoom:
        events = auto_zooms(events, tl.length, v.get('auto_zoom_scale', 1.8))
    keys = crop_track(events, tl, size, scale)

    out = clip_dir / 'clip.mp4'
    cmd = [
        ffmpeg(),
        '-y',
        '-v',
        'error',
        '-f',
        'rawvideo',
        '-pix_fmt',
        'rgb24',
        '-s',
        f'{OUT_W}x{OUT_H}',
        '-r',
        str(FPS),
        '-i',
        '-',
        '-c:v',
        'libx264',
        '-preset',
        'medium',
        '-crf',
        '15',
        '-pix_fmt',
        'yuv420p',
        str(out),
    ]
    pill = badge_image(badge, cfg) if badge else None
    ox, oy, dw = draw_origin(size)
    bg = '#' + cfg.get('brand', {}).get('background', '#18161C').lstrip('#')
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    last_key, last_bytes, cache = None, None, (None, None)
    n = round(duration * FPS)
    for k in range(n):
        t = k / FPS
        tv = tl.to_virtual(t)
        pos = bisect.bisect_right(vts_sorted, tv) - 1
        idx = order[max(pos, 0)]
        rect = stage_rect(rect_at(keys, t, size), size, focus)
        key = (idx, tuple(round(r, 1) for r in rect))
        if key != last_key:
            if cache[0] != idx:
                with Image.open(src_dir / 'frames' / frames[idx]['file']) as im:
                    cache = (idx, im.convert('RGB'))
            if VERTICAL and not is_native(size):
                shown = cache[1].resize(
                    (dw, round(dw * (rect[3] - rect[1]) / (rect[2] - rect[0]))),
                    Image.BICUBIC,
                    box=rect,
                    reducing_gap=2.0,
                )
                img = Image.new('RGB', (OUT_W, OUT_H), bg)
                img.paste(shown, (ox, oy))
            else:
                img = cache[1].resize(
                    (OUT_W, OUT_H), Image.BICUBIC, box=rect, reducing_gap=2.0
                )
            if pill:
                at = (
                    ((OUT_W - pill.width) // 2, BADGE_Y)
                    if VERTICAL
                    else (OUT_W - pill.width - 32, BADGE_Y)
                )
                img.paste(pill, at, pill)
            last_key, last_bytes = key, img.tobytes()
        proc.stdin.write(last_bytes)
    proc.stdin.close()
    if proc.wait() != 0:
        sys.exit(f'{clip_dir.name}: ffmpeg encode failed')
    meta = {
        'duration': round(n / FPS, 3),
        'narration_offset': lead,
        'narration_duration': audio,
        'overrun': round(max(tl.out_length - target, 0), 2),
        'trimmed': round(max(tl.out_length - duration, 0), 2),
        'cut_holds': round(sum(b - a for a, b in tlj['holds']), 2),
        'highlights': highlights(events, tl, keys, size, scale, focus),
        'sfx': [c for c in sound_cues(events, tl) if c['t'] < n / FPS],
    }
    write_json(clip_dir / 'clip.json', meta)
    return meta


def compose_video(
    clip_dir: Path,
    timing: dict,
    cfg: dict,
    src: str,
    start: float = 0.0,
    speed: float = 1.0,
    badge: str | None = None,
) -> dict:
    """
    Fit an external screen recording (e.g. Claude Desktop using the MCP connector) to its narration.

    The clip is scaled into 1920x1080 on the brand background, cut from `start`, sped up by `speed`,
    and its last frame held when it runs short; the disclosure pill is burned like on UI scenes.

    :param clip_dir: Path, scene directory to write clip.mp4 and clip.json into
    :param timing: dict, narration timing (duration)
    :param cfg: dict, full skill config
    :param src: str, path to the source video (~ allowed)
    :param start: float, seconds into the source where the scene starts
    :param speed: float, playback speed (1.5 = 50 % faster)
    :param badge: str | None, disclosure pill text
    :return: dict, clip metadata
    """
    src_path = Path(src).expanduser()
    if not src_path.exists():
        sys.exit(f'{clip_dir.name}: video src not found: {src_path}')
    clip_dir.mkdir(parents=True, exist_ok=True)
    v = cfg['video']
    lead, tail = v['scene_lead'], v['scene_tail']
    audio = timing.get('duration', 2.5)
    duration = lead + audio + tail
    bg = cfg.get('brand', {}).get('background', '#18161C').lstrip('#')
    chain = (
        f'[0:v]setpts=(PTS-STARTPTS)/{speed},fps={FPS},'
        f'scale={STAGE[2]}:{STAGE[3]}:force_original_aspect_ratio=decrease:flags=lanczos,'
        f'pad={OUT_W}:{OUT_H}:(ow-iw)/2:{STAGE[1]}+({STAGE[3]}-ih)/2:color=0x{bg},'
        f'tpad=stop_mode=clone:stop_duration={duration},setsar=1'
    )
    inputs = ['-ss', str(start), '-i', str(src_path)]
    if badge:
        pill = clip_dir / 'badge.png'
        badge_image(badge, cfg).save(pill)
        inputs += ['-i', str(pill)]
        chain += f'[b];[b][1:v]overlay={"(W-w)/2" if VERTICAL else "W-w-32"}:{BADGE_Y}[v]'
    else:
        chain += '[v]'
    out = clip_dir / 'clip.mp4'
    cmd = [ffmpeg(), '-y', '-v', 'error', *inputs, '-filter_complex', chain,
           '-map', '[v]', '-an', '-t', f'{duration:.3f}', '-c:v', 'libx264',
           '-preset', 'medium', '-crf', '15', '-pix_fmt', 'yuv420p', '-r', str(FPS), str(out)]
    if subprocess.run(cmd).returncode != 0:
        sys.exit(f'{clip_dir.name}: ffmpeg failed on {src_path}')
    meta = {
        'duration': round(round(duration * FPS) / FPS, 3),
        'narration_offset': lead,
        'narration_duration': audio,
        'overrun': 0,
        'trimmed': 0,
        'cut_holds': 0,
        'highlights': [],
    }
    write_json(clip_dir / 'clip.json', meta)
    return meta

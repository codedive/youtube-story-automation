"""Batch cinematic story renderer: Python stdlib + FFmpeg/FFprobe.

Usage: python video_generator.py --episode 1
Optional: --width 1280 --height 720 --fps 30 --transition 0.5
"""
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE_DIR = ROOT / 'images'
AUDIO_DIR = ROOT / 'music'
MUSIC_FILE = ROOT / 'music' / 'background.mp3'
VIDEO_DIR = ROOT / 'videos'
CACHE_DIR = ROOT / '.video_cache'
EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}


def run(cmd, label):
    print(f'  {label}', flush=True)
    proc = subprocess.run(cmd, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if proc.returncode:
        print(proc.stderr[-3500:], file=sys.stderr)
        raise RuntimeError(f'FFmpeg failed during {label}')


def probe_duration(path):
    proc = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                           '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                          capture_output=True, text=True, check=True)
    return float(proc.stdout.strip())


def scene_key(path):
    """Match Google Flow and MP3 names using episode and scene identifiers."""
    stem = path.stem
    match = re.search(
        r'episode[\s_:-]*(\d+)[\s_:-]+scene[\s_:-]*(\d+)([a-z]?)(?=$|[^a-z0-9])',
        stem, re.IGNORECASE
    )
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3).upper()


def sort_key(key):
    return key[1], key[2]


def index_files(directory, extensions, episode):
    found = {}
    if not directory.exists():
        return found
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.suffix.lower() not in extensions:
            continue
        key = scene_key(p)
        if key and key[0] == episode:
            if key in found:
                raise ValueError(f'Duplicate scene {key}: {found[key]} and {p}')
            found[key] = p
    return found


def concat_list(paths, target):
    # FFmpeg concat demuxer supports single-quoted escaped paths
    def quote(path):
        return str(path.resolve()).replace("'", "'\\''")
    target.write_text(''.join(f"file '{quote(p)}'\n" for p in paths), encoding='utf-8')


def render_scene(image, target, frames, fps, width, height, effect):
    # Render a 1.12x overscanned frame then pan across it; no artificial AI depth.
    # zoompan uses output frame index 'on'; d=1 creates one frame per input frame.
    total = max(1, frames - 1)
    if effect == 0:
        z = f'1.04+0.10*on/{total}'
        x = '(iw-iw/zoom)/2'
        y = '(ih-ih/zoom)/2'
    elif effect == 1:
        z = '1.12'
        x = f'(iw-iw/zoom)*on/{total}'
        y = '(ih-ih/zoom)/2'
    elif effect == 2:
        z = '1.12'
        x = f'(iw-iw/zoom)*(1-on/{total})'
        y = '(ih-ih/zoom)/2'
    elif effect == 3:
        z = '1.12'
        x = '(iw-iw/zoom)/2'
        y = f'(ih-ih/zoom)*on/{total}'
    else:
        z = f'1.14-0.10*on/{total}'
        x = '(iw-iw/zoom)/2'
        y = '(ih-ih/zoom)/2'

    # scale+crop fills 16:9 without distortion, zoompan creates camera motion.
    vf = (f'scale={width}:{height}:force_original_aspect_ratio=increase,'
          f'crop={width}:{height},'
          f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps},"
          'format=yuv420p')
    run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-loop', '1',
         '-framerate', str(fps), '-i', str(image), '-vf', vf,
         '-frames:v', str(frames), '-an', '-c:v', 'libx264',
         '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
         '-r', str(fps), '-video_track_timescale', '30000', str(target)],
        f'camera movement: {image.name}')


def render_chunk(clips, frame_counts, fade_frames, fps, dest, script_path):
    if len(clips) == 1:
        shutil.copyfile(clips[0], dest)
        return
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error']
    for clip in clips:
        cmd.extend(['-i', str(clip)])
    lines = []
    prev = '[0:v]'
    elapsed_frames = frame_counts[0]
    for i in range(1, len(clips)):
        out = f'[v{i}]'
        offset = elapsed_frames / fps
        lines.append(f'{prev}[{i}:v]xfade=transition=fade:duration={fade_frames/fps:.9f}:offset={offset:.9f}{out}')
        prev = out
        elapsed_frames += frame_counts[i]
    script_path.write_text(';\n'.join(lines), encoding='utf-8')
    cmd += ['-filter_complex', ';'.join(lines), '-map', prev,
            '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
            '-pix_fmt', 'yuv420p', '-r', str(fps),
            '-video_track_timescale', '30000', str(dest)]
    run(cmd, f'crossfade batch ({len(clips)} scenes)')


def main():
    parser = argparse.ArgumentParser(description='Auto cinematic video from named images + MP3')
    parser.add_argument('--episode', type=int, default=2)
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--transition', type=float, default=0.5)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    if args.width % 2 or args.height % 2 or args.fps <= 0 or args.batch < 1:
        parser.error('width/height must be even; fps/batch must be positive')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        sys.exit('Install FFmpeg and add ffmpeg + ffprobe to PATH first.')

    images = index_files(IMAGE_DIR, EXTS, args.episode)
    audios = index_files(AUDIO_DIR, {'.mp3', '.wav', '.m4a'}, args.episode)
    keys = sorted(images.keys() & audios.keys(), key=sort_key)
    for key in sorted(images.keys() - audios.keys(), key=sort_key):
        print(f'WARNING: Missing audio for scene {key}')
    for key in sorted(audios.keys() - images.keys(), key=sort_key):
        print(f'WARNING: Missing image for scene {key}')
    if not keys:
        sys.exit('No matching image/audio scenes found. Check images/ and output/.')
    VIDEO_DIR.mkdir(exist_ok=True)
    work = CACHE_DIR / f'episode_{args.episode}_{args.width}x{args.height}_{args.fps}fps'
    if args.rebuild and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    fps = args.fps
    fade = max(0, round(args.transition * fps))
    print(f'Found {len(keys)} matching scenes; crossfade {fade} frames')
    durations = [probe_duration(audios[k]) for k in keys]
    # Frame-align all voiceovers and scenes. Each scene gets >= 1 frame.
    counts = [max(1, math.ceil(d * fps)) for d in durations]
    video_batches = []
    narration_segments = []
    for start in range(0, len(keys), args.batch):
        chunk_keys = keys[start:start + args.batch]
        chunk_counts = counts[start:start + args.batch]
        clips = []
        for j, key in enumerate(chunk_keys):
            idx = start + j
            stem = f'{idx:05d}'
            wav = work / f'voice_{stem}.wav'
            # Convert each voice to a frame-aligned, constant-format PCM segment.
            if not wav.exists():
                run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                     '-i', str(audios[key]), '-af',
                     f'apad,atrim=duration={counts[idx]/fps:.9f},asetpts=PTS-STARTPTS',
                     '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(wav)],
                    f'voice sync: {audios[key].name}')
            narration_segments.append(wav)
            extra = fade if j < len(chunk_keys) - 1 else 0
            clip = work / f'clip_{stem}.mp4'
            if not clip.exists():
                render_scene(images[key], clip, counts[idx] + extra, fps,
                             args.width, args.height, idx % 5)
            clips.append(clip)
        chunk_file = work / f'batch_{start//args.batch:04d}.mp4'
        if not chunk_file.exists():
            render_chunk(clips, chunk_counts, fade, fps, chunk_file,
                         work / f'filter_{start//args.batch:04d}.txt')
        video_batches.append(chunk_file)

    video_list = work / 'video_list.txt'
    concat_list(video_batches, video_list)
    silent = work / 'silent_video.mp4'
    if not silent.exists():
        run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
             '-f', 'concat', '-safe', '0', '-i', str(video_list),
             '-c', 'copy', str(silent)], 'joining video batches')

    audio_list = work / 'audio_list.txt'
    concat_list(narration_segments, audio_list)
    narration = work / 'narration.wav'
    if not narration.exists():
        run(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
             '-f', 'concat', '-safe', '0', '-i', str(audio_list),
             '-c:a', 'pcm_s16le', str(narration)], 'joining narration')

    final = VIDEO_DIR / f'Episode {args.episode} - Full Movie.mp4'
    cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
           '-i', str(silent), '-i', str(narration)]
    if MUSIC_FILE.exists():
        cmd += ['-stream_loop', '-1', '-i', str(MUSIC_FILE),
                '-filter_complex',
                '[2:a]volume=0.12,aresample=48000[m];'
                '[m][1:a]sidechaincompress=threshold=0.035:ratio=8:attack=30:release=400[duck];'
                '[1:a][duck]amix=inputs=2:duration=first:normalize=0[a]',
                '-map', '0:v:0', '-map', '[a]']
    else:
        cmd += ['-map', '0:v:0', '-map', '1:a:0']
    cmd += ['-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', '-shortest', str(final)]
    run(cmd, 'final movie + music mix')
    print(f'\nDONE: {final}')
    print(f'Voiceover duration: {sum(counts)/fps:.1f} seconds')
    print('Tip: --rebuild deletes cached intermediate renders.')


if __name__ == '__main__':
    main()

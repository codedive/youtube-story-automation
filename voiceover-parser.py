"""voiceover-parser.py

Normalizes scene header lines in voiceovers.txt to the format:

    Episode <n> Scene <no>

It understands two source header styles found in this project's history:

  * Short form:      EP03_SC001_A
  * Verbose form:     Episode 2 : Scene 1A   /   Episode 2 - Scene 1A

...and rewrites every matching header to "Episode <n> Scene <no>" (e.g.
"Episode 1 Scene 1A"), where <n> defaults to 1 but can be overridden with
--episode, and <no> keeps the scene number + letter (e.g. "1A", "72B").

Usage:
    python voiceover-parser.py
    python voiceover-parser.py --episode 2
    python voiceover-parser.py --input voiceovers.txt --output voiceovers_clean.txt
    python voiceover-parser.py --dry-run
"""
import argparse
import re
import shutil
from pathlib import Path

# Short form: EP03_SC001_A (episode/scene numbers may or may not be zero-padded)
EP_SC_PATTERN = re.compile(
    r'^[ \t]*EP0*(\d+)_SC0*(\d+)_([A-Za-z])[ \t]*$',
    re.IGNORECASE | re.MULTILINE,
)

# Verbose form: "Episode 2 : Scene 1A", "Episode 2: Scene 1A", "Episode 2 - Scene 1A",
# "Episode 2 Scene 1A" (already normalized, re-running is safe/idempotent).
EPISODE_SCENE_PATTERN = re.compile(
    r'^[ \t]*Episode[ \t]+(\d+)[ \t]*[:\-]?[ \t]*Scene[ \t]+(\d+)([A-Za-z]?)[ \t]*$',
    re.IGNORECASE | re.MULTILINE,
)


def normalize_headers(content, episode=None):
    """Rewrite every scene header line to 'Episode <n> Scene <no>'.

    If `episode` is given, it overrides the episode number found in each
    header (useful since source file numbering doesn't always match the
    final episode being produced). Otherwise the episode number parsed
    from the header itself is kept.
    """
    # Count matches against the original content first, so a header rewritten
    # by one pattern isn't re-matched (and double-counted) by the other.
    changed = len(EP_SC_PATTERN.findall(content)) + len(EPISODE_SCENE_PATTERN.findall(content))

    def replace(match):
        parsed_episode, scene, letter = match.group(1), match.group(2), match.group(3)
        final_episode = episode if episode is not None else int(parsed_episode)
        return f"Episode {final_episode} Scene {int(scene)}{(letter or '').upper()}"

    content = EP_SC_PATTERN.sub(replace, content)
    content = EPISODE_SCENE_PATTERN.sub(replace, content)

    return content, changed


def main():
    parser = argparse.ArgumentParser(
        description='Normalize voiceover scene headers to "Episode <n> Scene <no>" format.'
    )
    parser.add_argument('--input', type=Path, default=Path('voiceovers.txt'),
                         help='Path to the voiceovers file (default: voiceovers.txt)')
    parser.add_argument('--output', type=Path, default=None,
                         help='Where to write the result (default: overwrite --input)')
    parser.add_argument('--episode', type=int, default=1,
                         help='Episode number to use in every header (default: 1). '
                              'Pass --episode -1 (or any negative) to instead keep '
                              'each header\'s own parsed episode number.')
    parser.add_argument('--dry-run', action='store_true',
                         help='Preview changes without writing any file')
    parser.add_argument('--no-backup', action='store_true',
                         help='Skip creating a .bak backup when overwriting --input in place')
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f'Input file not found: {args.input}')

    episode = None if args.episode < 0 else args.episode

    content = args.input.read_text(encoding='utf-8')
    new_content, changed = normalize_headers(content, episode)

    print(f'Headers normalized: {changed}')

    if args.dry_run:
        print('--- dry run: preview of first 10 normalized headers ---')
        count = 0
        for line in new_content.splitlines():
            if line.strip().lower().startswith('episode'):
                print(line)
                count += 1
                if count >= 10:
                    break
        return

    output_path = args.output or args.input

    if output_path == args.input and not args.no_backup:
        backup_path = args.input.with_suffix(args.input.suffix + '.bak')
        shutil.copy2(args.input, backup_path)
        print(f'Backup written to {backup_path}')

    output_path.write_text(new_content, encoding='utf-8')
    print(f'Updated file written to {output_path}')


if __name__ == '__main__':
    main()

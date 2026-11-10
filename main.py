
import asyncio
import re
from pathlib import Path
import edge_tts

# Configuration
INPUT_FILE = Path("voiceovers.txt")
OUTPUT_DIR = Path("music")

VOICE = "hi-IN-MadhurNeural"  # Hindi Male
RATE = "-5%"
VOLUME = "+0%"

async def generate_voiceover(name, text):
    output_file = OUTPUT_DIR / f"{name}.mp3"

    if output_file.exists():
        print(f"Skipped: {name}")
        return

    for attempt in range(3):
        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=VOICE,
                rate=RATE,
                volume=VOLUME
            )

            await communicate.save(str(output_file))
            print(f"Generated: {output_file}")
            return

        except Exception as error:
            print(f"Attempt {attempt + 1}: {error}")
            await asyncio.sleep(3)

    print(f"Failed: {name}")

def read_scenes(content):
    # Supports Scene 1, 1A, 1B, 12C, etc. Separator between "Episode N" and
    # "Scene X" is optional so both "Episode 1 Scene 1A" and the older
    # "Episode 1 : Scene 1A" / "Episode 1 - Scene 1A" headers still parse.
    pattern = (
        r"(?im)^\s*Episode\s+(\d+)\s*[:\-]?\s*"
        r"Scene\s+(\d+[A-Z]*)\s*$"
    )

    matches = list(re.finditer(pattern, content))
    scenes = []

    for index, match in enumerate(matches):
        start = match.end()

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(content)
        )

        episode = int(match.group(1))
        scene = match.group(2).upper()
        text = content[start:end].strip()

        if text:
            name = f"Episode {episode} - Scene {scene}"
            scenes.append((name, text))

    return scenes

async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    content = INPUT_FILE.read_text(encoding="utf-8")
    scenes = read_scenes(content)

    print(f"Total voiceovers found: {len(scenes)}")

    for name, text in scenes:
        await generate_voiceover(name, text)

    print("All voiceovers completed!")

if __name__ == "__main__":
    asyncio.run(main())

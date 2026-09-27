"""One-time public model download; never downloads or uploads user audio."""
from pathlib import Path
from faster_whisper.utils import download_model

if __name__ == '__main__':
    destination = Path(__file__).resolve().parents[1] / '.models' / 'tiny.en'
    download_model('tiny.en', output_dir=str(destination))
    print(f'Local English speech model ready: {destination}')

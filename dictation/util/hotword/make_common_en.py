"""Write common_en.txt, the common-English word list the sound-alike matcher uses.

Not used at runtime. Regenerate with wordfreq installed (pip install wordfreq) from the repo root:
    python -m util.hotword.make_common_en
"""
import re
from importlib.metadata import version
from pathlib import Path

ZIPF_MIN = 3.0   # about once per million words: roughly the 30,000 most common words


def main() -> None:
    from wordfreq import top_n_list, zipf_frequency

    words = sorted({w for w in top_n_list('en', 80000)
                    if re.fullmatch(r'[a-z]+', w) and zipf_frequency(w, 'en') >= ZIPF_MIN})
    out = Path(__file__).with_name('common_en.txt')
    with open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'# Common English words: wordfreq {version("wordfreq")}, zipf frequency >= {ZIPF_MIN} '
                f'(word data CC BY-SA 4.0). Made by make_common_en.py.\n')
        f.write('# A heard phrase made only of these words needs the full hot_thresh score to be replaced.\n')
        f.write('\n'.join(words) + '\n')
    print(f'{len(words)} words -> {out}')


if __name__ == '__main__':
    main()

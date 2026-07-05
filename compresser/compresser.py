import os
from pathlib import Path
from PIL import Image

SRC_DIR = "images"
DST_DIR = "images_webp"

def convert_to_webp(src_path: Path, dst_path: Path):
    img = Image.open(src_path)

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    img.save(
        dst_path,
        format="WEBP",
        lossless=True,   # без потери качества, пиксель в пиксель
        quality=100,      # для lossless влияет на скорость/степень сжатия, не на качество
        method=6,         # 0-6, максимальное усилие сжатия (медленнее, но лучше жмёт)
    )

def main():
    src_dir = Path(SRC_DIR)
    dst_dir = Path(DST_DIR)

    total_before = 0
    total_after = 0

    for file in src_dir.rglob("*.png"):
        rel = file.relative_to(src_dir)
        out_path = (dst_dir / rel).with_suffix(".webp")

        convert_to_webp(file, out_path)

        before = file.stat().st_size
        after = out_path.stat().st_size
        total_before += before
        total_after += after

        print(f"{rel}: {before/1024:.0f} KB -> {after/1024:.0f} KB "
              f"(-{100*(1-after/before):.1f}%)")

    if total_before:
        print("\nИтого:")
        print(f"{total_before/1024/1024:.2f} MB -> {total_after/1024/1024:.2f} MB "
              f"(-{100*(1-total_after/total_before):.1f}%)")

if __name__ == "__main__":
    main()
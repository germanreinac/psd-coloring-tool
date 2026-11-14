"""Download a page from Google Drive by its share link: python -m megalith_flats.fetch "<link>"

The file must be shared as 'Anyone with the link'. It is saved into 'whole project/' next to the
tool, which the tool treats as read-only, and its path is printed.
"""
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def file_id(link):
    m = re.search(r"/d/([\w-]{20,})", link) or re.search(r"[?&]id=([\w-]{20,})", link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w-]{20,}", link.strip()):
        return link.strip()
    raise SystemExit(f"Could not find a Drive file id in: {link}")


def download(link, folder=None, name=None, log=print):
    fid = file_id(link)
    folder = folder or os.path.join(HERE, "whole project")
    os.makedirs(folder, exist_ok=True)
    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".part")
    os.close(fd)
    hdr = tmp + ".headers"
    try:
        r = subprocess.run(["curl", "-sS", "-L", "--fail", "--retry", "3", "-o", tmp, "-D", hdr, url],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"Download failed ({r.stderr.strip()}). Is the file shared as 'Anyone with the link', "
                             "and are drive.google.com / drive.usercontent.google.com allowed in this environment?")
        headers = open(hdr, encoding="latin-1").read()
        with open(tmp, "rb") as f:
            head = f.read(512)
        if b"<html" in head.lower() or b"<!doctype" in head.lower():
            raise SystemExit("Drive sent a web page instead of the file. Share it as 'Anyone with the link' and retry.")
        if not name:
            m = re.findall(r"filename\*=UTF-8''([^;\r\n]+)", headers) or re.findall(r'filename="([^"]+)"', headers)
            name = urllib.parse.unquote(m[-1]) if m else f"{fid}.psd"
        dest = os.path.join(folder, os.path.basename(name))
        os.replace(tmp, dest)
        log(f"Downloaded {dest} ({os.path.getsize(dest) / 1e6:.0f} MB)")
        return dest
    finally:
        for p in (tmp, hdr):
            if os.path.exists(p):
                os.remove(p)


if __name__ == "__main__":
    print(download(sys.argv[1], name=sys.argv[2] if len(sys.argv) > 2 else None))

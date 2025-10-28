# =============================
# Google Colab Torrent Downloader
# Optimized + Multithreaded + Speed Boosted
# =============================

import os
import time
import datetime
import threading
from tqdm import tqdm
from colorama import Fore, Style
import libtorrent as lt

# ---- Default Save Path ----
SAVE_PATH = "/content/drive/My Drive/Torrents"
os.makedirs(SAVE_PATH, exist_ok=True)


# ---- Start Session ----
def start_session():
    ses = lt.session()
    ses.listen_on(6881, 6891)
    ses.start_dht()
    return ses


# ---- Add Torrent / Magnet ----
def add_torrent(ses, link_or_path, save_path):
    params = {
        'save_path': save_path,
        'storage_mode': lt.storage_mode_t.storage_mode_sparse
    }
    if link_or_path.startswith("magnet:"):
        handle = lt.add_magnet_uri(ses, link_or_path, params)
    else:
        info = lt.torrent_info(link_or_path)
        handle = ses.add_torrent({'ti': info, 'save_path': save_path})
    return handle


# ---- ETA Formatter ----
def format_eta(seconds):
    mins, secs = divmod(int(seconds), 60)
    return f"{mins:02d}:{secs:02d}"


# ---- Download Worker ----
def download_worker(handle, pbar):
    while not handle.is_seed():
        status = handle.status()

        # Update progress bar
        pbar.update(status.total_done - pbar.n)

        # Live stats
        download_speed = status.download_rate / 1024
        upload_speed = status.upload_rate / 1024
        seeders = status.num_seeds
        peers = status.num_peers
        remaining = status.total_wanted - status.total_done
        eta = format_eta(remaining / status.download_rate) if status.download_rate > 0 else "∞"

        pbar.set_postfix({
            "Down": f"{download_speed:.1f} KB/s",
            "Up": f"{upload_speed:.1f} KB/s",
            "Seeds": seeders,
            "Peers": peers,
            "ETA": eta
        })

        time.sleep(1)

    # Completed
    print(Fore.GREEN + f"\n[✔] {handle.name()} COMPLETED!" + Style.RESET_ALL)
    pbar.close()


# ---- Main Download Function ----
def download_torrents():
    ses = start_session()
    links = input(Fore.CYAN + "Enter Magnet Links or Torrent Paths (comma separated): " + Style.RESET_ALL).split(",")

    handles = []
    for link in links:
        link = link.strip()
        if not link:
            continue
        print(Fore.YELLOW + f"[*] Adding torrent: {link}" + Style.RESET_ALL)
        handle = add_torrent(ses, link, SAVE_PATH)
        handles.append(handle)

    print(Fore.MAGENTA + "\n[*] Fetching metadata...\n" + Style.RESET_ALL)
    for handle in handles:
        while not handle.has_metadata():
            time.sleep(1)
        print(Fore.GREEN + f"[+] Metadata fetched for: {handle.name()}" + Style.RESET_ALL)

    print(Fore.CYAN + "\n[*] Starting Downloads...\n" + Style.RESET_ALL)
    threads = []
    for handle in handles:
        pbar = tqdm(
            total=handle.get_torrent_info().total_size(),
            unit="B", unit_scale=True, unit_divisor=1024,
            desc=handle.name()[:25]
        )
        t = threading.Thread(target=download_worker, args=(handle, pbar))
        t.start()
        threads.append(t)

    # Wait for all downloads to finish
    for t in threads:
        t.join()

    print(Fore.MAGENTA + "\n[+] All torrents downloaded successfully!" + Style.RESET_ALL)
    print(Fore.YELLOW + f"Saved at: {SAVE_PATH}" + Style.RESET_ALL)


# ---- Run ----
download_torrents()

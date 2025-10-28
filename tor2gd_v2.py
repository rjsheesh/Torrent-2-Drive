import os
import time
import threading
import signal
import libtorrent as lt
from tqdm import tqdm
from colorama import Fore, Style

# ---------- Config ----------
MAX_WORKERS = 6  # concurrent download threads
TQDM_LOCK = threading.Lock()
stop_event = threading.Event()

def get_save_path():
    # Priority: env var -> cwd (safe) -> script dir -> /tmp
    env = os.environ.get("TORRENT_SAVE_PATH")
    if env:
        path = env
    else:
        try:
            cwd = os.getcwd()
        except Exception:
            cwd = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.environ.get('PWD') or '/tmp'
        path = os.path.join(cwd, "Torrents")
    os.makedirs(path, exist_ok=True)
    return path

SAVE_PATH = get_save_path()


# ----- Start Session -----
def start_session():
    ses = lt.session()
    ses.listen_on(6881, 6891)

    # Performance Boost Settings
    settings = ses.get_settings()
    settings['alert_mask'] = (
        lt.alert.category_t.status_notification |
        lt.alert.category_t.error_notification
    )
    settings['active_downloads'] = 100
    settings['active_seeds'] = 100
    settings['connections_limit'] = 500
    settings['download_rate_limit'] = 0   # Unlimited
    settings['upload_rate_limit'] = 0     # Unlimited
    settings['request_timeout'] = 10
    settings['peer_connect_timeout'] = 5
    settings['send_buffer_watermark'] = 10 * 1024 * 1024
    settings['send_buffer_low_watermark'] = 1 * 1024 * 1024
    settings['send_buffer_watermark_factor'] = 150
    settings['read_cache_line_size'] = 512
    settings['file_pool_size'] = 200

    ses.apply_settings(settings)
    try:
        ses.start_dht()
    except Exception:
        # Some envs may not allow DHT; ignore if fails
        pass
    return ses


# ----- Add Torrent or Magnet Link -----
def add_torrent(ses, link_or_path, save_path):
    params = {
        'save_path': save_path,
        'storage_mode': lt.storage_mode_t.storage_mode_sparse,
        'flags': lt.torrent_flags.auto_managed | lt.torrent_flags.sequential_download
    }

    if link_or_path.startswith("magnet:"):
        handle = lt.add_magnet_uri(ses, link_or_path, params)
    else:
        info = lt.torrent_info(link_or_path)
        handle = ses.add_torrent({'ti': info, 'save_path': save_path})
    return handle


# ----- ETA Formatter -----
def format_eta(seconds):
    try:
        if seconds is None or seconds == float('inf') or seconds < 0:
            return "∞"
        seconds = int(seconds)
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h:d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"
    except Exception:
        return "∞"


# ----- Download Worker (thread-safe with tqdm lock) -----
def download_worker(handle, pbar):
    while not stop_event.is_set() and not handle.is_seed():
        try:
            status = handle.status()
        except Exception as e:
            with TQDM_LOCK:
                tqdm.write(f"{Fore.RED}[!] Failed to read status: {e}{Style.RESET_ALL}")
            break

        # Safe update of progress bar
        with TQDM_LOCK:
            delta = int(status.total_done - pbar.n)
            if delta > 0:
                pbar.update(delta)

            download_speed = status.download_rate / 1024  # KB/s
            upload_speed = status.upload_rate / 1024
            seeders = getattr(status, "num_seeds", 0)
            peers = getattr(status, "num_peers", 0)
            remaining = max(0, int(status.total_wanted - status.total_done))
            eta = format_eta(remaining / status.download_rate) if status.download_rate > 0 else "∞"

            pbar.set_postfix({
                "Down": f"{download_speed:.1f} KB/s",
                "Up": f"{upload_speed:.1f} KB/s",
                "Seeds": seeders,
                "Peers": peers,
                "ETA": eta
            })

        time.sleep(0.5)

    # Completed or stopped
    with TQDM_LOCK:
        if handle.is_seed():
            tqdm.write(Fore.GREEN + f"\n[✔] {handle.name()} COMPLETED!" + Style.RESET_ALL)
        else:
            tqdm.write(Fore.YELLOW + f"\n[!] {handle.name()} stopped." + Style.RESET_ALL)
        pbar.close()


# ----- Main Download Function -----
def download_torrents():
    ses = start_session()
    raw = input(Fore.CYAN + "Enter Magnet Links or Torrent Paths (comma separated): " + Style.RESET_ALL).strip()
    if not raw:
        print(Fore.YELLOW + "No links provided. Exiting." + Style.RESET_ALL)
        return

    links = [l.strip() for l in raw.split(",") if l.strip()]
    handles = []

    for link in links:
        print(Fore.YELLOW + f"[*] Adding torrent: {link}" + Style.RESET_ALL)
        try:
            handle = add_torrent(ses, link, SAVE_PATH)
            handles.append(handle)
        except Exception as e:
            print(Fore.RED + f"[!] Failed to add {link}: {e}" + Style.RESET_ALL)

    if not handles:
        print(Fore.RED + "No valid torrents to download." + Style.RESET_ALL)
        return

    print(Fore.MAGENTA + "\n[*] Fetching metadata...\n" + Style.RESET_ALL)
    for handle in handles:
        while not stop_event.is_set() and not handle.has_metadata():
            time.sleep(1)
        try:
            name = handle.name()
        except Exception:
            name = "<unknown>"
        print(Fore.GREEN + f"[+] Metadata fetched for: {name}" + Style.RESET_ALL)

    print(Fore.CYAN + "\n[*] Starting Downloads...\n" + Style.RESET_ALL)
    threads = []
    sem = threading.BoundedSemaphore(MAX_WORKERS)

    def worker_wrapper(h):
        sem.acquire()
        try:
            # get total, may raise if no metadata - fallback to 0
            try:
                total = h.get_torrent_info().total_size()
            except Exception:
                total = None
            desc = (h.name()[:40]) if total is not None else h.name()[:40]
            pbar = tqdm(
                total=total or 0,
                unit="B", unit_scale=True, unit_divisor=1024,
                desc=desc, leave=True
            )
            download_worker(h, pbar)
        finally:
            sem.release()

    for handle in handles:
        t = threading.Thread(target=worker_wrapper, args=(handle,), daemon=True)
        t.start()
        threads.append(t)

    # Wait for all downloads or stop_event
    try:
        for t in threads:
            while t.is_alive():
                t.join(timeout=0.5)
                if stop_event.is_set():
                    break
    except KeyboardInterrupt:
        stop_event.set()

    if stop_event.is_set():
        print(Fore.YELLOW + "\n[!] Downloads interrupted by user." + Style.RESET_ALL)
    else:
        print(Fore.MAGENTA + "\n[+] All torrents processed." + Style.RESET_ALL)

    print(Fore.YELLOW + f"Saved at: {SAVE_PATH}" + Style.RESET_ALL)


# Signal handler for graceful stop
def _signal_handler(signum, frame):
    print(Fore.YELLOW + "\n[!] Received interrupt - stopping..." + Style.RESET_ALL)
    stop_event.set()

signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ----- Run -----
if __name__ == "__main__":
    download_torrents()

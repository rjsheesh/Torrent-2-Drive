import os

# === CONFIG ===
# ড্রাইভে কোথায় সেভ হবে
DRIVE_PATH = "/content/drive/MyDrive/Torrents"
# লোকাল টেম্প ফোল্ডার
SAVE_PATH = "/content/Torrents"

# === FUNCTION ===
def download_with_aria2(torrent_link):
    # ফোল্ডার বানানো
    os.makedirs(SAVE_PATH, exist_ok=True)
    os.makedirs(DRIVE_PATH, exist_ok=True)

    print("🚀 Download starting with aria2...")

    # Aria2 দিয়ে ডাউনলোড (মাল্টি কানেকশন)
    cmd = f'aria2c -x 16 -s 16 -d "{SAVE_PATH}" "{torrent_link}"'
    os.system(cmd)

    print("📂 Moving files to Google Drive...")
    os.system(f'mv "{SAVE_PATH}"/* "{DRIVE_PATH}/"')

    print("✅ Download complete and moved to Drive!")

# === MAIN ===
if __name__ == "__main__":
    torrent_link = input("👉 Enter Torrent/Magnet Link: ").strip()
    if torrent_link:
        download_with_aria2(torrent_link)
    else:
        print("⚠️ No torrent link provided!")

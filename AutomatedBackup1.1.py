import os
import subprocess
import threading
import json
from ftplib import FTP
from tkinter import *
from tkinter import filedialog, scrolledtext, ttk

CONFIG_PATH = os.path.expanduser("~/.switch_backup_config.json")

def log(msg):
    console.configure(state='normal')
    console.insert(END, msg + '\n')
    console.configure(state='disabled')
    console.yview(END)

def browse_folder():
    folder = filedialog.askdirectory()
    if folder:
        entry_local.delete(0, END)
        entry_local.insert(0, folder)

def create_rclone_config(mega_email, mega_password, config_name):
    try:
        cmd = [
            "rclone", "config", "create", config_name, "mega",
            "user", mega_email,
            "pass", mega_password
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            log(f"[✓] Rclone config '{config_name}' created.")
            return True
        else:
            log(f"[✗] Failed to create rclone config:\n{result.stderr}")
            return False
    except Exception as e:
        log(f"[!] Failed to create rclone config: {e}")
        return False

def download_if_new(ftp, ftp_path, local_dir, game_name):
    updated = False
    try:
        ftp.cwd(ftp_path)
        files = list(ftp.mlsd())
        for name, facts in files:
            if facts.get("type") != "file":
                continue
            local_file = os.path.join(local_dir, name)
            ftp_size = int(facts.get("size", 0))
            if os.path.exists(local_file) and os.path.getsize(local_file) == ftp_size:
                continue
            updated = True
            os.makedirs(local_dir, exist_ok=True)
            with open(local_file, "wb") as f:
                ftp.retrbinary(f"RETR {name}", f.write)
    except Exception as e:
        log(f"[!] Error downloading from {ftp_path}: {e}")
    if updated:
        log(f"[++] Updated game folder: {game_name}")

def on_password_change(*args):
    pwd = mega_pass_var.get()
    if pwd.strip() == "":
        entry_rclone.config(state='disabled')
    else:
        entry_rclone.config(state='normal')
    validate_rclone_name()

def validate_rclone_name(*args):
    name = entry_rclone.get().strip()
    if name == "":
        btn_start_backup.config(state='disabled')
    else:
        btn_start_backup.config(state='normal')

def save_config():
    config = {
        "ip": entry_ip.get().strip(),
        "port": entry_port.get().strip(),
        "rclone": entry_rclone.get().strip(),
        "email": entry_email.get().strip(),
        "local": entry_local.get().strip()
    }
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    except Exception as e:
        log(f"[!] Failed to save config: {e}")

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                config = json.load(f)
                entry_ip.insert(0, config.get("ip", ""))
                entry_port.insert(0, config.get("port", ""))
                entry_rclone.insert(0, config.get("rclone", ""))
                entry_email.insert(0, config.get("email", ""))
                entry_local.insert(0, config.get("local", os.path.expanduser("~/switch_saves")))
        except:
            pass
    else:
        entry_ip.insert(0, "ENTER YOUR IP HERE")
        entry_port.insert(0, "5000")
        entry_rclone.insert(0, "mega")
        entry_local.insert(0, os.path.expanduser("~/switch_saves"))

def update_progress(value):
    progress["value"] = value
    root.update_idletasks()

def backup_thread():
    switch_ip = entry_ip.get().strip()
    try:
        switch_port = int(entry_port.get())
    except:
        log("[!] Invalid port number.")
        btn_start_backup.config(state='normal')
        return

    rclone_remote = entry_rclone.get().strip()
    mega_email = entry_email.get().strip()
    mega_pass = mega_pass_var.get()
    local_dir = entry_local.get().strip()

    btn_start_backup.config(state='disabled')
    update_progress(0)
    log("[*] Starting backup...")

    save_config()

    if mega_pass.strip() != "":
        log("[*] Creating rclone config...")
        if not create_rclone_config(mega_email, mega_pass, rclone_remote):
            log("[✗] Could not create rclone config. Check credentials.")
            btn_start_backup.config(state='normal')
            update_progress(0)
            return
    else:
        log("[*] Using existing rclone config.")

    os.makedirs(local_dir, exist_ok=True)
    latest_dir = local_dir

    ftp_save_dir = "/Installed games"
    local_save_dir = os.path.join(latest_dir, "Installed")
    os.makedirs(local_save_dir, exist_ok=True)

    try:
        log(f"[*] Connecting to Switch {switch_ip}:{switch_port}")
        ftp = FTP()
        ftp.connect(switch_ip, switch_port, timeout=10)
        ftp.login('anonymous', 'anonymous')

        ftp.cwd(ftp_save_dir)
        subdirs = [name for name, facts in ftp.mlsd() if facts.get("type") == "dir"]

        total = len(subdirs)
        for i, game_dir in enumerate(subdirs, 1):
            log(f"[+] Processing game folder: {game_dir}")
            update_progress((i / total) * 50)  # 50% progress allocated to download
            ftp_game_dir = f"{ftp_save_dir}/{game_dir}"
            try:
                ftp.cwd(ftp_game_dir)
                user_subdirs = [name for name, facts in ftp.mlsd() if facts.get("type") == "dir"]

                if not user_subdirs:
                    local_subdir = os.path.join(local_save_dir, game_dir)
                    download_if_new(ftp, ftp_game_dir, local_subdir, game_dir)
                else:
                    for user_subdir in user_subdirs:
                        ftp_user_dir = f"{ftp_game_dir}/{user_subdir}"
                        local_subdir = os.path.join(local_save_dir, game_dir, user_subdir)
                        download_if_new(ftp, ftp_user_dir, local_subdir, game_dir)
            except Exception as e:
                log(f"[!] Skipping {ftp_game_dir}: {e}")

        ftp.quit()

        log("[✓] Files downloaded. Uploading to cloud...")
        update_progress(70)

        cloud_path = f"{rclone_remote}:SwitchSaves/Installed"

        rclone_result = subprocess.run(
            ["rclone", "copy", "--size-only", local_save_dir, cloud_path],
            capture_output=True, text=True
        )

        update_progress(100)

        if rclone_result.returncode == 0:
            log(f"[✓] Upload complete: {cloud_path}")
        else:
            log(f"[✗] Rclone failed to upload:\n{rclone_result.stderr}")

    except Exception as e:
        log(f"[!] Error: {e}")

    btn_start_backup.config(state='normal')
    update_progress(0)

def start_backup():
    threading.Thread(target=backup_thread, daemon=True).start()

# GUI Setup
root = Tk()
root.title("Switch Backup Tool")

frame = Frame(root)
frame.pack(padx=10, pady=10)

Label(frame, text="Switch IP:").grid(row=0, column=0, sticky=E)
entry_ip = Entry(frame)
entry_ip.grid(row=0, column=1)

Label(frame, text="Switch Port:").grid(row=1, column=0, sticky=E)
entry_port = Entry(frame)
entry_port.grid(row=1, column=1)

Label(frame, text="Rclone Config Name:").grid(row=2, column=0, sticky=E)
entry_rclone = Entry(frame)
entry_rclone.grid(row=2, column=1)

Label(frame, text="MEGA Email:").grid(row=3, column=0, sticky=E)
entry_email = Entry(frame)
entry_email.grid(row=3, column=1)

Label(frame, text="MEGA Password:").grid(row=4, column=0, sticky=E)
mega_pass_var = StringVar()
entry_pass = Entry(frame, show="*", textvariable=mega_pass_var)
entry_pass.grid(row=4, column=1)

Label(frame, text="Local Backup Folder:").grid(row=5, column=0, sticky=E)
entry_local = Entry(frame, width=30)
entry_local.grid(row=5, column=1)
Button(frame, text="Browse", command=browse_folder).grid(row=5, column=2, padx=5)

btn_start_backup = Button(root, text="Start Backup", command=start_backup)
btn_start_backup.pack(pady=5)

console = scrolledtext.ScrolledText(root, height=10, state='disabled', wrap=WORD)
console.pack(fill=BOTH, padx=10, pady=10, expand=True)

progress = ttk.Progressbar(root, mode='determinate', maximum=100)
progress.pack(fill=X, padx=10, pady=(0, 10))

mega_pass_var.trace_add('write', on_password_change)
entry_rclone.bind('<KeyRelease>', validate_rclone_name)

load_config()
on_password_change()
validate_rclone_name()

root.mainloop()


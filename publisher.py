import os
import time
import requests

def upload_instagram_reel(video_path, caption, config):
    """
    Uploads a local .mp4 video as an Instagram Reel using Meta's Resumable Upload API.
    """
    meta_cfg = config.get("meta", {})
    ig_user_id = meta_cfg.get("instagram_id")
    page_token = meta_cfg.get("page_token")

    if not ig_user_id or not page_token:
        return False, "Missing Instagram user ID or access token."

    file_size = os.path.getsize(video_path)
    print(f"[*] Starting Instagram Reel upload ({file_size / (1024*1024):.2f} MB)...")

    # Step 1: Initialize Resumable Upload Container
    init_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
    init_payload = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "access_token": page_token
    }

    try:
        r_init = requests.post(init_url, data=init_payload, timeout=30)
        res_init = r_init.json()
    except Exception as e:
        return False, f"Network error creating Reel container: {e}"

    if "id" not in res_init or "uri" not in res_init:
        return False, f"Failed initializing Reel container: {res_init}"

    creation_id = res_init["id"]
    upload_uri = res_init["uri"]
    print(f"    - Container ID: {creation_id}")

    # Step 2: Upload Video Bytes to Resumable URI
    headers = {
        "Authorization": f"OAuth {page_token}",
        "offset": "0",
        "file_size": str(file_size)
    }

    try:
        with open(video_path, "rb") as f:
            r_up = requests.post(upload_uri, headers=headers, data=f, timeout=180)
            res_up = r_up.json()
    except Exception as e:
        return False, f"Error streaming video bytes: {e}"

    if not res_up.get("success", False):
        return False, f"Video binary upload failed: {res_up}"

    print("    - Video bytes uploaded. Polishing container status...")

    # Step 3: Poll Container Status until FINISHED
    status_url = f"https://graph.facebook.com/v22.0/{creation_id}"
    params = {"fields": "status_code,status", "access_token": page_token}
    ready = False

    for attempt in range(25):
        time.sleep(4)
        try:
            r_st = requests.get(status_url, params=params, timeout=20)
            st_data = r_st.json()
            status_code = st_data.get("status_code", "")
            print(f"    - Status check {attempt + 1}: {status_code}")

            if status_code == "FINISHED":
                ready = True
                break
            elif status_code == "ERROR":
                return False, f"Instagram video processing error: {st_data}"
        except Exception as e:
            print(f"    - Status polling glitch: {e}")

    if not ready:
        return False, "Timeout waiting for Instagram to process Reel video."

    # Step 4: Publish Reel Container
    pub_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media_publish"
    pub_payload = {"creation_id": creation_id, "access_token": page_token}

    try:
        r_pub = requests.post(pub_url, data=pub_payload, timeout=30)
        res_pub = r_pub.json()
        if "id" in res_pub:
            post_id = res_pub["id"]
            print(f"[+] Instagram Reel Published Successfully! Post ID: {post_id}")
            return True, f"https://www.instagram.com/reel/{post_id}"
        else:
            return False, f"Instagram publish rejected: {res_pub}"
    except Exception as e:
        return False, f"Publish request failed: {e}"


def upload_facebook_video(video_path, caption, config):
    """
    Uploads a video to the connected Facebook Page.
    """
    meta_cfg = config.get("meta", {})
    page_id = meta_cfg.get("page_id")
    page_token = meta_cfg.get("page_token")

    if not page_id or not page_token:
        return False, "Missing Facebook Page ID or Token."

    url = f"https://graph.facebook.com/v22.0/{page_id}/videos"
    data = {
        "description": caption,
        "access_token": page_token
    }

    print("[*] Uploading video to Facebook Page...")
    try:
        with open(video_path, "rb") as f:
            files = {"source": f}
            r = requests.post(url, data=data, files=files, timeout=120)
            res = r.json()

        if "id" in res:
            post_id = res["id"]
            print(f"[+] Facebook Video Published Successfully! ID: {post_id}")
            return True, post_id
        else:
            return False, f"Facebook video publish failed: {res}"
    except Exception as e:
        return False, f"Facebook upload error: {e}"
